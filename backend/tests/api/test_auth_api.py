"""Route-level tests for `/api/v1/auth/*` and `/api/v1/me`.

All DB and Google network calls are monkey-patched so these run as
fast unit tests against FastAPI's TestClient.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.google import GoogleIdentity
from app.services.users import User


@pytest.fixture
def patched_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-oauth-client")
    monkeypatch.setenv("SESSION_SECRET", "unit-test-secret-1234567890abcdef")
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")

    from app.config import reset_settings_cache

    reset_settings_cache()

    from app.api import auth_api

    store: dict[str, User] = {}
    # The real backend stores the allowlist in its own `auth_allowlist`
    # table, independent of `users`. We model that here as a separate
    # set so deleting a user (which only touches `users`) doesn't
    # accidentally also drop the email from the allowlist — that's the
    # property `test_delete_account_does_not_remove_email_from_allowlist`
    # is asserting.
    allowlist: set[str] = {"allowed@example.com", "admin@example.com"}

    def fake_is_email_allowed(email: str, *, settings) -> bool:  # noqa: ARG001
        return email.lower() in allowlist

    def fake_upsert(identity: GoogleIdentity) -> User:
        user = User(
            id=len(store) + 1,
            google_sub=identity.sub,
            apple_sub=None,
            email=identity.email,
            name=identity.name,
            picture_url=identity.picture,
        )
        store[identity.email.lower()] = user
        return user

    def fake_get_user_by_email(email: str) -> User | None:
        return store.get(email.lower())

    def fake_get_user_by_id(user_id: int) -> User | None:
        for u in store.values():
            if u.id == user_id:
                return u
        return None

    def fake_delete_user(user_id: int) -> bool:
        # Mirror the real service's signature: returns True iff a row
        # was removed. We mutate `store` so subsequent fake lookups
        # (`get_user_by_id`, `get_user_by_email`) honour the deletion
        # — same effect as the CASCADE FKs in prod: from the
        # application's point of view, the user is just *gone*.
        target_email: str | None = None
        for email, user in store.items():
            if user.id == user_id:
                target_email = email
                break
        if target_email is None:
            return False
        del store[target_email]
        return True

    monkeypatch.setattr(auth_api, "is_email_allowed", fake_is_email_allowed)
    monkeypatch.setattr(auth_api, "upsert_user_from_google", fake_upsert)
    monkeypatch.setattr(auth_api, "get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr(auth_api, "delete_user", fake_delete_user)

    from app.auth import dependencies as deps_mod

    monkeypatch.setattr(deps_mod, "get_user_by_id", fake_get_user_by_id)

    monkeypatch.setattr(
        auth_api,
        "verify_google_id_token",
        lambda token, settings: GoogleIdentity(  # noqa: ARG005
            sub="google-sub-allow" if token == "good" else "google-sub-denied",
            email=("allowed@example.com" if token == "good" else "stranger@example.com"),
            email_verified=True,
            name="Allowed" if token == "good" else "Stranger",
            picture=None,
        ),
    )
    # Seed the allowlist for our happy-path test email.
    store.setdefault(
        "allowed@example.com",
        User(
            id=1,
            google_sub="pre-seed",
            apple_sub=None,
            email="allowed@example.com",
            name="Allowed",
            picture_url=None,
        ),
    )

    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client


def test_me_is_anonymous_without_cookie(patched_app: TestClient) -> None:
    r = patched_app.get("/api/v1/me")
    assert r.status_code == 200
    assert r.json() == {"user": None}


def test_google_login_sets_session_cookie(patched_app: TestClient) -> None:
    r = patched_app.post("/api/v1/auth/google", json={"credential": "good"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "allowed@example.com"

    # Session cookie should now be set; /me returns the user.
    r2 = patched_app.get("/api/v1/me")
    assert r2.status_code == 200
    assert r2.json()["email"] == "allowed@example.com"


def test_google_login_respects_allowlist(patched_app: TestClient) -> None:
    r = patched_app.post("/api/v1/auth/google", json={"credential": "stranger"})
    assert r.status_code == 403
    assert "allowlist" in r.json()["detail"].lower()


def test_logout_clears_cookie(patched_app: TestClient) -> None:
    patched_app.post("/api/v1/auth/google", json={"credential": "good"})
    r = patched_app.post("/api/v1/auth/logout")
    assert r.status_code == 200
    # `/me` is anonymous again.
    assert patched_app.get("/api/v1/me").json() == {"user": None}


def test_dev_login_rejects_non_allowlisted(patched_app: TestClient) -> None:
    r = patched_app.post(
        "/api/v1/auth/dev-login", json={"email": "stranger@example.com"}
    )
    assert r.status_code == 403


def test_dev_login_accepts_allowlisted(patched_app: TestClient) -> None:
    r = patched_app.post(
        "/api/v1/auth/dev-login",
        json={"email": "allowed@example.com", "name": "Allowed Dev"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "allowed@example.com"


def test_auth_config_exposes_client_id(patched_app: TestClient) -> None:
    r = patched_app.get("/api/v1/auth/config")
    assert r.status_code == 200
    body = r.json()
    assert body["google_oauth_client_id"] == "test-oauth-client"
    assert body["dev_login_enabled"] is True


def test_login_omits_session_token_for_web_clients(
    patched_app: TestClient,
) -> None:
    """Default response shape (no `X-Client` header, no `?token=true`)
    must NOT leak the JWT in the body — web clients use the cookie."""
    r = patched_app.post("/api/v1/auth/google", json={"credential": "good"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_token"] is None
    assert body["session_expires_at"] is None
    assert "tlh_session" in r.cookies


def test_login_returns_session_token_for_mobile_header(
    patched_app: TestClient,
) -> None:
    """`X-Client: mobile` opts the response into bearer-token mode for
    Expo / React Native clients that can't rely on cookies."""
    r = patched_app.post(
        "/api/v1/auth/google",
        json={"credential": "good"},
        headers={"X-Client": "mobile"},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["session_token"], str)
    assert body["session_token"].count(".") == 2  # JWT shape (h.p.s)
    assert isinstance(body["session_expires_at"], str)
    # Cookie is still set as well, so the same endpoint serves both
    # cookie- and bearer-style consumers transparently.
    assert "tlh_session" in r.cookies


def test_login_returns_session_token_for_query_param(
    patched_app: TestClient,
) -> None:
    """`?token=true` is the manual / dev-console opt-in equivalent of
    the `X-Client: mobile` header."""
    r = patched_app.post(
        "/api/v1/auth/google?token=true",
        json={"credential": "good"},
    )
    assert r.status_code == 200
    assert isinstance(r.json()["session_token"], str)


def test_dev_login_returns_session_token_for_mobile_header(
    patched_app: TestClient,
) -> None:
    r = patched_app.post(
        "/api/v1/auth/dev-login",
        json={"email": "allowed@example.com"},
        headers={"X-Client": "mobile"},
    )
    assert r.status_code == 200
    assert isinstance(r.json()["session_token"], str)


def test_bearer_token_authenticates_subsequent_requests(
    patched_app: TestClient,
) -> None:
    """A mobile client signs in once, persists the JWT, and uses it as
    `Authorization: Bearer <jwt>` on every subsequent request — no
    cookie required."""
    r = patched_app.post(
        "/api/v1/auth/google",
        json={"credential": "good"},
        headers={"X-Client": "mobile"},
    )
    assert r.status_code == 200
    token = r.json()["session_token"]
    assert token

    # Drop cookies so we can prove the bearer header alone is enough.
    patched_app.cookies.clear()
    r2 = patched_app.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r2.status_code == 200
    assert r2.json()["email"] == "allowed@example.com"


def test_bearer_token_with_garbage_value_is_anonymous(
    patched_app: TestClient,
) -> None:
    """Malformed / unknown JWTs are silently treated as anonymous so
    `/me` keeps its 200 + `{user: null}` contract."""
    r = patched_app.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r.status_code == 200
    assert r.json() == {"user": None}


def test_non_bearer_authorization_scheme_is_ignored(
    patched_app: TestClient,
) -> None:
    """Anything other than the Bearer scheme is treated as no
    credential — no 500, no scheme-confusion attack surface."""
    r = patched_app.get(
        "/api/v1/me",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert r.status_code == 200
    assert r.json() == {"user": None}


# --- Account deletion ----------------------------------------------------
# Apple App Review Guideline 5.1.1(v) requires every app that supports
# account creation to also support in-app account deletion. The DELETE
# /api/v1/me route is the single server-side hook the mobile + web
# clients call.


def test_delete_account_requires_auth(patched_app: TestClient) -> None:
    """Anonymous callers can't nuke arbitrary accounts. 401, not 403 —
    'go log in' is the right next-step message for the SPA."""
    r = patched_app.delete("/api/v1/me")
    assert r.status_code == 401


def test_delete_account_wipes_user_and_clears_session(
    patched_app: TestClient,
) -> None:
    """Happy path: signed-in user calls DELETE /me ->
        * 204 No Content
        * session cookie cleared on the response (so the browser
          stops sending it on the next request)
        * /me with the (now-stale) cookie returns anonymous, because
          the user row no longer exists -> get_user_by_id returns
          None -> get_optional_user returns None.
    """
    patched_app.post("/api/v1/auth/google", json={"credential": "good"})
    assert "tlh_session" in patched_app.cookies

    r = patched_app.delete("/api/v1/me")
    assert r.status_code == 204, r.text
    assert r.content == b""

    # The Set-Cookie clearing instruction is what makes the web
    # client forget the session as part of the same response.
    set_cookies = r.headers.get_list("set-cookie")
    assert any(
        "tlh_session=" in c and ("Max-Age=0" in c or "expires=Thu, 01 Jan 1970" in c.lower())
        for c in set_cookies
    ), f"expected a clearing Set-Cookie, got {set_cookies!r}"

    # Even without the clearing header (e.g. a mobile client that
    # ignores cookies), the bearer token / cookie no longer
    # resolves to a user because the row is gone.
    me = patched_app.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json() == {"user": None}


def test_delete_account_with_bearer_token_invalidates_subsequent_requests(
    patched_app: TestClient,
) -> None:
    """Mobile flow: log in with `X-Client: mobile` to get a JWT, hold
    on to it, then DELETE /me with that bearer header. The next
    request that presents the same (cryptographically still-valid)
    bearer token is treated as anonymous because the underlying
    user row no longer exists — same guarantee web gets via cookie
    clearing, without needing a server-side blocklist."""
    login = patched_app.post(
        "/api/v1/auth/google",
        json={"credential": "good"},
        headers={"X-Client": "mobile"},
    )
    token = login.json()["session_token"]
    assert token

    auth = {"Authorization": f"Bearer {token}"}
    # Sanity check: the bearer auths /me right now.
    r0 = patched_app.get("/api/v1/me", headers=auth)
    assert r0.status_code == 200
    assert r0.json()["email"] == "allowed@example.com"

    # Drop cookies so we're exclusively on the bearer path.
    patched_app.cookies.clear()

    r = patched_app.delete("/api/v1/me", headers=auth)
    assert r.status_code == 204, r.text

    # Stale-but-cryptographically-valid bearer should now degrade to
    # anonymous on every subsequent request, with no extra server
    # state needed (no JWT denylist, no Redis, nothing).
    r2 = patched_app.get("/api/v1/me", headers=auth)
    assert r2.status_code == 200
    assert r2.json() == {"user": None}


def test_delete_account_does_not_remove_email_from_allowlist(
    patched_app: TestClient,
) -> None:
    """The allowlist is operator-controlled, not user-controlled.
    Deleting your account leaves the email on the allowlist so the
    *same person* can sign in again (with the same provider) and
    get a fresh user row. The deleted trips / samples / audit log
    do not come back — that's the contract."""
    patched_app.post("/api/v1/auth/google", json={"credential": "good"})
    r = patched_app.delete("/api/v1/me")
    assert r.status_code == 204

    # Same provider + same email -> fresh user row (note: in the
    # real backend this is a brand-new `id`; the fake `upsert`
    # increments by len(store)+1 which now equals 1 again because
    # the dict was emptied. The behaviour we care about is that
    # sign-in *succeeds*, not the specific id.)
    r2 = patched_app.post("/api/v1/auth/google", json={"credential": "good"})
    assert r2.status_code == 200
    assert r2.json()["email"] == "allowed@example.com"
