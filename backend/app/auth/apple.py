"""Apple Sign In identity-token verification.

The mobile flow:
    1. The iOS client invokes `expo-apple-authentication` →
       AuthenticationServices.framework, which produces an `identityToken`
       (JWT signed by Apple).
    2. The frontend POSTs it to `POST /api/v1/auth/apple`.
    3. We verify it here with PyJWT against Apple's published JWKs
       (rotating ES256 keys at https://appleid.apple.com/auth/keys).
    4. The verifier returns an `AppleIdentity` and the endpoint upserts
       the user + issues a session token, identical to the Google path.

Why we don't use a third-party "apple-auth" library:
    The verification is small and the JWK fetch + ES256 signature check
    are first-class in PyJWT (which we already depend on for our own
    session JWTs). One less transitive dep, one less attack surface.

Apple-specific quirks worth knowing:
    - The `email` claim is only present on the *first* sign-in for a
      given user. After that, we re-identify the user by `sub`. So our
      caller (users service) must accept `email is None` and fall back
      to a stored `apple_sub` lookup.
    - When a user opts into Apple's "Hide My Email" relay, `email` is
      a stable @privaterelay.appleid.com address. That's fine for our
      allowlist + login flow as long as the operator allowlists it.
    - `email_verified` is a string `"true"`/`"false"` (not a bool) on
      Apple's tokens, in violation of OIDC spec. We coerce.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock

import jwt
import requests
from jwt import PyJWKClient

from app.config import Settings

logger = logging.getLogger(__name__)


class InvalidAppleIdentityTokenError(Exception):
    """Raised when an Apple identity token cannot be verified."""


@dataclass(frozen=True)
class AppleIdentity:
    """Claims we trust from a verified Apple identity token.

    `email` is `None` after the first sign-in (Apple's privacy
    behaviour). Callers must fall back to `sub`-based lookup.

    `is_private_email` is true when the user picked Apple's
    "Hide My Email" option at sign-in, which means `email` is a
    per-app `@privaterelay.appleid.com` proxy address rather than
    the user's real address. We don't reject these sign-ins (Apple
    expects apps to support Hide-My-Email), but the flag is
    surfaced so the frontend can warn users that cross-provider
    linking via email won't work for this account.
    """

    sub: str
    email: str | None
    email_verified: bool
    is_private_email: bool


_APPLE_ISSUER = "https://appleid.apple.com"
_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
# How long to cache Apple's JWKs in-process. Apple rotates keys
# infrequently (~yearly) and PyJWKClient handles a cache miss
# transparently by re-fetching, so a long TTL is safe. Keep the
# value short enough that a forced rotation after a key compromise
# would propagate within an hour even without a process restart.
_JWKS_TTL_SECONDS = 60 * 60

_jwks_lock = Lock()
_jwks_client: PyJWKClient | None = None
_jwks_fetched_at: float = 0.0


def _get_jwks_client() -> PyJWKClient:
    """Process-wide cached `PyJWKClient` for Apple's signing keys."""
    global _jwks_client, _jwks_fetched_at
    with _jwks_lock:
        now = time.monotonic()
        if (
            _jwks_client is None
            or (now - _jwks_fetched_at) > _JWKS_TTL_SECONDS
        ):
            _jwks_client = PyJWKClient(_APPLE_JWKS_URL, cache_keys=True)
            _jwks_fetched_at = now
        return _jwks_client


def verify_apple_identity_token(
    token: str, settings: Settings
) -> AppleIdentity:
    """Validate an Apple identity token and return the claims we trust.

    Verifies the ES256 signature against Apple's JWKs, plus issuer +
    audience + expiry. The audience must match `apple_oauth_client_id`
    (typically the iOS bundle ID, e.g. `com.time2leave.app`).
    """
    expected_audience = settings.apple_oauth_client_id
    if not expected_audience:
        raise InvalidAppleIdentityTokenError(
            "APPLE_OAUTH_CLIENT_ID is not configured on the backend"
        )

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    except (
        # `get_signing_key_from_jwt` first parses the JWT header to read
        # the `kid`, which raises `jwt.DecodeError` (a `PyJWTError`
        # subclass) for malformed-shape tokens. Without this catch the
        # endpoint 500s on any client that POSTs garbage instead of a
        # JWT — which masks real server bugs and gives the mobile
        # button no chance to render a "try again" message. PyJWKClientError
        # covers JWK-server / cache issues; RequestException covers
        # transport failures during the JWK fetch.
        jwt.PyJWTError,
        jwt.PyJWKClientError,
        requests.RequestException,
    ) as exc:
        logger.info("Failed to validate Apple token / fetch JWK: %s", exc)
        raise InvalidAppleIdentityTokenError(
            "Could not validate Apple identity token"
        ) from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            # Apple signs identity tokens with RS256 (RSA-SHA256).
            # Their JWKs at https://appleid.apple.com/auth/keys are
            # all RSA keys, not EC keys — the JWT spec allows EC
            # variants but Apple has historically only used RS256
            # for sign-in-with-apple. Pinning the list keeps us
            # safe from algorithm-confusion attacks.
            algorithms=["RS256"],
            audience=expected_audience,
            issuer=_APPLE_ISSUER,
            options={"require": ["sub", "iss", "aud", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        logger.info("Rejecting Apple identity token: %s", exc)
        raise InvalidAppleIdentityTokenError(str(exc)) from exc

    sub = claims.get("sub")
    if not sub:
        raise InvalidAppleIdentityTokenError("Apple token missing sub")

    raw_email = claims.get("email")
    email = str(raw_email).lower() if raw_email else None

    # Apple ships `email_verified` as a string, not a bool. Treat
    # missing or "false" as not verified; treat `True` and "true" as
    # verified. The Hide-My-Email relay address is always verified.
    email_verified = _coerce_apple_bool(claims.get("email_verified"))

    # `is_private_email` is "true" when the user opted into
    # Hide-My-Email, in which case `email` is a per-app
    # `@privaterelay.appleid.com` proxy. Apple documents this as
    # always-a-string, but in practice the JWT decoders sometimes
    # see a real bool, so we coerce both shapes.
    is_private_email = _coerce_apple_bool(claims.get("is_private_email"))

    return AppleIdentity(
        sub=str(sub),
        email=email,
        email_verified=email_verified,
        is_private_email=is_private_email,
    )


def _coerce_apple_bool(value: object) -> bool:
    """Apple JWT booleans arrive as `"true"` / `"false"` strings (per
    their docs) or as real bools (in some PyJWT versions); coerce
    both shapes, defaulting to False for anything else (missing,
    malformed, or unexpected types)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return False
