"""Unit tests for `app.auth.apple.verify_apple_identity_token`.

These tests exercise the token-shape validation path *before* any
network call to Apple's JWKs endpoint. They cover the latent bug
where a malformed (non-JWT) `token` argument used to leak as a
`jwt.DecodeError` and surface to the route handler as HTTP 500 —
the route's contract is HTTP 401 for any invalid token.
"""

from __future__ import annotations

import jwt
import pytest

from app.auth.apple import (
    InvalidAppleIdentityTokenError,
    verify_apple_identity_token,
)
from app.config import Settings


def _settings(audience: str = "com.example.app") -> Settings:
    """Build a `Settings` instance with the minimum config the verifier
    inspects (`apple_oauth_client_id`). All other env-derived fields
    fall back to their defaults / empty values, which is fine because
    the verifier short-circuits before reading them."""
    return Settings(apple_oauth_client_id=audience)


def test_rejects_completely_malformed_token() -> None:
    """A non-JWT string ("not.enough.segments") used to slip past the
    `(PyJWKClientError, RequestException)` catch and raise
    `jwt.DecodeError`, which the FastAPI route then leaked as 500.
    PyJWT raises `DecodeError` before any HTTP call is made to Apple,
    so this assertion is fully offline."""
    with pytest.raises(InvalidAppleIdentityTokenError):
        verify_apple_identity_token("garbage", _settings())


def test_rejects_token_with_wrong_segment_count() -> None:
    """Same failure mode, slightly different shape: a string that
    *looks* like base64 but doesn't have the three JWT segments."""
    with pytest.raises(InvalidAppleIdentityTokenError):
        verify_apple_identity_token("a.b", _settings())


def test_rejects_token_with_invalid_base64_header() -> None:
    """Three dot-separated segments, but the header isn't valid
    base64-encoded JSON. PyJWT raises `DecodeError`; verifier must
    swallow it."""
    with pytest.raises(InvalidAppleIdentityTokenError):
        verify_apple_identity_token("!!!.!!!.!!!", _settings())


def test_missing_audience_config_short_circuits() -> None:
    """If the operator forgot to configure `APPLE_OAUTH_CLIENT_ID`, the
    verifier refuses to even look at the token — Apple sign-in is
    disabled at the config layer."""
    with pytest.raises(InvalidAppleIdentityTokenError):
        verify_apple_identity_token("anything", _settings(audience=""))


def test_decodeerror_is_pyjwterror_subclass() -> None:
    """Regression guard: the fix relies on `jwt.DecodeError` being a
    subclass of `jwt.PyJWTError` so the broader catch covers it. If
    PyJWT ever reorganises its exception hierarchy this assertion
    will fail loudly before the wrong tokens start 500-ing again."""
    assert issubclass(jwt.DecodeError, jwt.PyJWTError)
