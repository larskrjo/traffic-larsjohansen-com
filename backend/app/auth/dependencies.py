"""FastAPI dependencies that turn a session cookie into a User row.

Route handlers use one of:
    * `current_user` — require a logged-in user; 401 otherwise.
    * `admin_user`   — require a logged-in user whose email is in `admin_emails`.
    * `optional_user` — accept anonymous callers; returns `None` if so.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, status

from app.auth.sessions import (
    InvalidSessionError,
    SessionClaims,
    verify_session_token,
)
from app.config import Settings, get_settings
from app.services.users import User, get_user_by_id


def _cookie_name() -> str:
    return get_settings().session_cookie_name


def _session_claims_from_token(
    token: str | None, settings: Settings
) -> SessionClaims | None:
    """Decode a session JWT (cookie value or bearer token), tolerating
    invalid/expired tokens by returning None instead of raising."""
    if not token:
        return None
    try:
        return verify_session_token(token, settings)
    except InvalidSessionError:
        return None


def _bearer_token(authorization_header: str | None) -> str | None:
    """Extract `<jwt>` from an `Authorization: Bearer <jwt>` header.

    Returns None for missing, malformed, or non-Bearer schemes — the
    caller treats that the same as "no credentials presented".
    """
    if not authorization_header:
        return None
    parts = authorization_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    candidate = parts[1].strip()
    return candidate or None


def get_optional_user(
    tlh_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Return the current user from a cookie *or* bearer token.

    Web clients ship a `tlh_session` HttpOnly cookie set on the
    `/api/v1/auth/google` response; mobile clients (Expo / React
    Native) opt out of cookies and instead send
    `Authorization: Bearer <jwt>` using the same JWT format. Cookie
    wins when both are present so that nothing changes for the SPA.

    Note: the `tlh_session` parameter name must match
    `Settings.session_cookie_name`. We keep the default name in sync via
    tests; changing the setting at runtime would also need a matching
    parameter here if you want anonymous callers to be identified.
    """
    claims = _session_claims_from_token(tlh_session, settings)
    if claims is None:
        claims = _session_claims_from_token(
            _bearer_token(authorization), settings
        )
    if claims is None:
        return None
    return get_user_by_id(claims.user_id)


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    """Require an authenticated user; raise 401 otherwise."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def is_admin(user: User, settings: Settings) -> bool:
    """Return True iff `user.email` is in `settings.admin_emails`.

    Single source of truth for admin checks — used by `get_admin_user`,
    by `_serialize_user` (to expose `is_admin` to the SPA), and by the
    trip-quota path (admins get a higher per-user trip cap).
    """
    return user.email.lower() in {a.lower() for a in settings.admin_emails}


def is_review_account_email(email: str | None, settings: Settings) -> bool:
    """Return True iff `email` belongs to a configured App Store / Play
    Store reviewer account.

    Reviewer accounts run on the deterministic `FixtureProvider` and
    skip the Geocoding pre-flight so that the create-trip / delete-
    account / re-create-trip loop reviewers exercise during App Store
    review costs $0 instead of $16.80/cycle in Google Maps spend.

    `email` is `Optional` so callers that have only `user.email` (a
    `str`) and callers that have raw DB values (which could in theory
    be None) can both feed it in safely. Comparison is case-insensitive
    because `settings.review_account_emails` is already lowercased by
    the `_split_email_lists` validator.
    """
    if not email:
        return False
    return email.lower() in {e.lower() for e in settings.review_account_emails}


def is_review_account(user: User, settings: Settings) -> bool:
    """`User`-typed convenience wrapper around `is_review_account_email`."""
    return is_review_account_email(user.email, settings)


def get_admin_user(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> User:
    """Require an authenticated user whose email is in `admin_emails`."""
    if not is_admin(user, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
