"""HTTP-level auth endpoints: /auth/google, /auth/logout, /auth/dev-login, /me.

The frontend flow:
    1. GSI library produces an ID token client-side.
    2. Frontend POSTs it to /api/v1/auth/google.
    3. We verify it, check the allowlist, upsert the user, and set a
       session cookie. Subsequent requests authenticate via the cookie.
    4. /api/v1/auth/logout clears the cookie.
    5. /api/v1/me returns the logged-in user (or 401 if not).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.auth.apple import (
    InvalidAppleIdentityTokenError,
    verify_apple_identity_token,
)
from app.auth.dependencies import get_current_user, get_optional_user, is_admin
from app.auth.google import InvalidGoogleIdTokenError, verify_google_id_token
from app.auth.sessions import (
    clear_session_cookie,
    issue_session_token,
    set_session_cookie,
)
from app.config import Settings, get_settings
from app.services.allowlist import is_email_allowed
from app.services.users import (
    AppleIdentityWithoutLinkError,
    User,
    delete_user,
    get_user_by_email,
    upsert_user_from_apple,
    upsert_user_from_google,
)

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/v1", tags=["Auth"])


class GoogleLoginRequest(BaseModel):
    credential: str = Field(..., description="Google ID token from GSI")


class AppleLoginRequest(BaseModel):
    """Body posted by the iOS client after `expo-apple-authentication`
    completes. `identity_token` is the JWT signed by Apple; `name` is
    populated *only* on the first authorization for a given user (per
    Apple's privacy design). The backend never trusts `name` for
    identity decisions — it's stored as the user's display name on
    first sign-up and otherwise ignored."""

    identity_token: str = Field(
        ..., description="JWT identity token from AuthenticationServices"
    )
    name: str | None = None


class DevLoginRequest(BaseModel):
    email: EmailStr
    name: str | None = None


class AuthedUserResponse(BaseModel):
    id: int
    email: EmailStr
    name: str | None
    picture_url: str | None
    is_admin: bool
    # Bearer-token fields populated only for clients that opt in via
    # `X-Client: mobile` or `?token=true`. Web clients ignore these and
    # rely on the HttpOnly `tlh_session` cookie instead.
    session_token: str | None = None
    session_expires_at: str | None = None


def _serialize_user(user: User, settings: Settings) -> AuthedUserResponse:
    return AuthedUserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        picture_url=user.picture_url,
        is_admin=is_admin(user, settings),
    )


def _wants_session_token(
    request: Request, x_client: str | None
) -> bool:
    """Should this login response include the bearer-token fields?

    Mobile clients can opt in either via the explicit `X-Client: mobile`
    header (preferred — works on every request, not just login) or with
    a `?token=true` query param (handy from a browser console for ad-hoc
    testing). Web stays on the cookie path by default."""
    if x_client and x_client.strip().lower() == "mobile":
        return True
    return request.query_params.get("token", "").lower() == "true"


def _attach_session(
    *,
    user: User,
    settings: Settings,
    response: Response,
    include_token_in_body: bool,
) -> AuthedUserResponse:
    """Issue a session JWT, write it to the cookie, and (when the
    caller opted in) echo it back in the response body so a mobile
    client without cookie storage can persist it itself."""
    token, expires_at = issue_session_token(
        user_id=user.id, email=user.email, settings=settings
    )
    set_session_cookie(response, token, expires_at, settings)
    payload = _serialize_user(user, settings)
    if include_token_in_body:
        payload.session_token = token
        payload.session_expires_at = expires_at.isoformat()
    return payload


@auth_router.post("/auth/google")
async def login_with_google(
    body: GoogleLoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    x_client: str | None = Header(default=None),
) -> AuthedUserResponse:
    """Exchange a Google ID token for a session cookie (web) or a bearer
    token (mobile, via `X-Client: mobile` / `?token=true`)."""
    try:
        identity = verify_google_id_token(body.credential, settings)
    except InvalidGoogleIdTokenError as exc:
        logger.info("Google login rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google credential",
        ) from exc

    if not identity.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google account email is not verified",
        )

    if not is_email_allowed(identity.email, settings=settings):
        logger.info("Login blocked by allowlist: %s", identity.email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This email is not on the allowlist. Ask the owner to add "
                "you and try again."
            ),
        )

    user = upsert_user_from_google(identity)
    return _attach_session(
        user=user,
        settings=settings,
        response=response,
        include_token_in_body=_wants_session_token(request, x_client),
    )


@auth_router.post("/auth/apple")
async def login_with_apple(
    body: AppleLoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    x_client: str | None = Header(default=None),
) -> AuthedUserResponse:
    """Exchange a Sign-in-with-Apple identity token for a session.

    Mirrors `/auth/google`: verify the JWT, enforce the allowlist on
    the user's email, upsert the user row, and issue a session
    token (cookie for web, bearer for `X-Client: mobile`).

    Apple-specific behaviour:
      - Email is only delivered on the *first* authorization for a
        given user. On subsequent sign-ins the token has no email
        claim; we identify the user by `apple_sub` instead. If the
        first ever sign-in arrives without an email *and* we have
        no row keyed on the same `sub`, we 400 with a clear error
        instead of silently creating an unidentifiable account.
      - The allowlist is checked only when an email is present.
        Once a user is on the allowlist for their first sign-in,
        subsequent token-only sign-ins (no email) are accepted on
        the basis of the existing row.
    """
    try:
        identity = verify_apple_identity_token(body.identity_token, settings)
    except InvalidAppleIdentityTokenError as exc:
        logger.info("Apple login rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Apple credential",
        ) from exc

    if identity.email is not None:
        if not identity.email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apple account email is not verified",
            )
        if not is_email_allowed(identity.email, settings=settings):
            logger.info("Login blocked by allowlist: %s", identity.email)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This email is not on the allowlist. Ask the owner to add "
                    "you and try again."
                ),
            )

    try:
        user = upsert_user_from_apple(identity, name=body.name)
    except AppleIdentityWithoutLinkError as exc:
        logger.warning("Apple sign-in without identifiable user: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Could not identify your Apple account. Please go to "
                "iOS Settings → Apple ID → Sign In with Apple → "
                "time2leave → Stop Using Apple ID, then try again."
            ),
        ) from exc

    return _attach_session(
        user=user,
        settings=settings,
        response=response,
        include_token_in_body=_wants_session_token(request, x_client),
    )


@auth_router.post("/auth/dev-login")
async def dev_login(
    body: DevLoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    x_client: str | None = Header(default=None),
) -> AuthedUserResponse:
    """Escape hatch for local dev / tests when no real GSI is available.

    Only mounted when `APP_ENV != "prod"` and `ENABLE_DEV_LOGIN` is truthy.
    Requires the email to already be on the allowlist or a known user, so
    an accidentally-exposed dev endpoint still can't log in a stranger.
    Honors `X-Client: mobile` so the Expo dev build can use the same
    bearer-token round trip as a production login.
    """
    if settings.app_env == "prod" or not settings.enable_dev_login:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )

    email = body.email.lower()
    if not is_email_allowed(email, settings=settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email is not on the dev allowlist",
        )

    user = get_user_by_email(email)
    if user is None:
        # Dev convenience: conjure a user row so the rest of the app works.
        from app.auth.google import GoogleIdentity

        identity = GoogleIdentity(
            sub=f"dev-{email}",
            email=email,
            email_verified=True,
            name=body.name,
            picture=None,
        )
        user = upsert_user_from_google(identity)

    return _attach_session(
        user=user,
        settings=settings,
        response=response,
        include_token_in_body=_wants_session_token(request, x_client),
    )


@auth_router.post("/auth/logout")
async def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Drop the session cookie. Idempotent (safe to call anonymously)."""
    clear_session_cookie(response, settings)
    return {"status": "ok"}


@auth_router.get("/me")
async def get_me(
    user: User | None = Depends(get_optional_user),
    settings: Settings = Depends(get_settings),
) -> AuthedUserResponse | dict[str, None]:
    """Return the authenticated user, or `{"user": null}` for anonymous."""
    if user is None:
        return {"user": None}
    return _serialize_user(user, settings)


@auth_router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    response: Response,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Permanently delete the authenticated user and all their data.

    Effects, atomically:
      * `users` row removed.
      * All their `trips` removed (CASCADE).
      * All `commute_samples` for those trips removed (CASCADE via
        `trips.id` -> `commute_samples.trip_id`).
      * All `trip_mutation_log` rows for the user removed (CASCADE).
      * Session cookie cleared on the response. A stale bearer
        token kept by a mobile client also degrades to anonymous
        on the next request because the underlying user row is
        gone (see `delete_user` docstring).

    This endpoint exists so the mobile + web "Delete account"
    flows have one server-side call to make. It's a hard
    requirement of Apple App Review (Guideline 5.1.1(v), "apps
    that support account creation must offer account deletion in
    app") — without this route, every iOS submission gets
    rejected.

    Idempotency: the route returns 204 whether or not the row
    actually existed at the moment of the DELETE — a duplicate
    request from a confused client is indistinguishable from a
    successful first one, which is what the UI wants.
    """
    delete_user(user.id)
    clear_session_cookie(response, settings)
    logger.info("Deleted account for user id=%s email=%s", user.id, user.email)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@auth_router.get("/auth/config")
async def auth_config(
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Client-safe OAuth config so the SPA doesn't need a separate env var flow."""
    return {
        "google_oauth_client_id": settings.google_oauth_client_id,
        "apple_sign_in_enabled": bool(settings.apple_oauth_client_id),
        "dev_login_enabled": settings.enable_dev_login
        and settings.app_env != "prod",
    }


__all__ = ["auth_router", "get_current_user"]
