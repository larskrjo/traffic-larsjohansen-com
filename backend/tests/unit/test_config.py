"""Unit tests for app.config."""

from __future__ import annotations

import os

import pytest

from app.config import Settings, get_settings, reset_settings_cache


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("APP_") or key.startswith("MYSQL_") or key.startswith(
            "DATA_"
        ) or key == "DEVELOPMENT_MODE" or key == "GOOGLE_MAPS_API_KEY":
            monkeypatch.delenv(key, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_defaults_are_local():
    s = Settings()
    assert s.app_env == "local"
    assert s.mysql_host == "localhost"
    assert s.data_provider == "fixture"


def test_legacy_development_mode_prod_is_aliased(monkeypatch):
    monkeypatch.setenv("DEVELOPMENT_MODE", "prod")
    reset_settings_cache()
    # We don't want to actually hit AWS, so just assert the env alias got applied.
    from app.config import _apply_legacy_env_aliases

    _apply_legacy_env_aliases()
    assert os.environ.get("APP_ENV") == "prod"


def test_explicit_app_env_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DEVELOPMENT_MODE", "prod")
    reset_settings_cache()
    s = get_settings()
    assert s.app_env == "local"


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "db.example.com")
    monkeypatch.setenv("MYSQL_PORT", "4242")
    monkeypatch.setenv("DATA_PROVIDER", "google")
    reset_settings_cache()
    s = get_settings()
    assert s.mysql_host == "db.example.com"
    assert s.mysql_port == 4242
    assert s.data_provider == "google"


def test_google_oauth_client_ids_splits_comma_separated():
    """A single env var carries the web + iOS + Android client IDs;
    `google_oauth_client_ids` exposes them as a list for the audience
    check in `verify_google_id_token`."""
    s = Settings(
        google_oauth_client_id="web-id,  ios-id ,android-id,web-id"
    )
    assert s.google_oauth_client_ids == ["web-id", "ios-id", "android-id"]


def test_google_oauth_client_ids_empty_when_unset():
    assert Settings(google_oauth_client_id=None).google_oauth_client_ids == []
    assert Settings(google_oauth_client_id="").google_oauth_client_ids == []


def test_google_oauth_client_ids_handles_single_value():
    s = Settings(google_oauth_client_id="only-one")
    assert s.google_oauth_client_ids == ["only-one"]


def test_review_account_emails_splits_comma_separated(monkeypatch):
    """Env-var carries multiple reviewer emails as a comma list,
    matching the ADMIN_EMAILS / AUTH_ALLOWLIST_BOOTSTRAP convention."""
    monkeypatch.setenv(
        "REVIEW_ACCOUNT_EMAILS",
        "my.app.store.reviewer@gmail.com , Play.Reviewer@Example.com",
    )
    reset_settings_cache()
    s = get_settings()
    assert s.review_account_emails == [
        "my.app.store.reviewer@gmail.com",
        "play.reviewer@example.com",
    ]


def test_review_account_emails_default_empty():
    assert Settings().review_account_emails == []


def test_review_account_emails_constructor_accepts_list():
    """Programmatic construction (used in tests) should also accept a
    list[str], not just the comma-separated env var form."""
    s = Settings(review_account_emails=["A@B.com", "c@d.com"])
    assert s.review_account_emails == ["a@b.com", "c@d.com"]
