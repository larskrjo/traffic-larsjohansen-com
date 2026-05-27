"""Unit tests for commute providers."""

from __future__ import annotations

import pytest
import responses

from app.config import Settings
from app.job.providers import (
    ROUTES_MATRIX_URL,
    FixtureProvider,
    GoogleRoutesProvider,
    get_provider,
    provider_for_user_email,
)


class TestFixtureProvider:
    def test_deterministic(self):
        p = FixtureProvider()
        a = p.fetch("San Jose", "San Francisco", "2025-11-10T08:00:00-08:00")
        b = p.fetch("San Jose", "San Francisco", "2025-11-10T08:00:00-08:00")
        assert a == b

    def test_h2w_vs_w2h_differ(self):
        p = FixtureProvider()
        h2w = p.fetch("San Jose", "San Francisco", "2025-11-10T08:00:00-08:00")
        w2h = p.fetch("San Francisco", "San Jose", "2025-11-10T17:30:00-08:00")
        assert h2w.duration != w2h.duration

    def test_duration_is_seconds_string(self):
        p = FixtureProvider()
        r = p.fetch("San Jose", "SF", "2025-11-10T08:00:00-08:00")
        assert r.duration is not None and r.duration.endswith("s")
        assert int(r.duration[:-1]) > 0

    def test_status_ok(self):
        p = FixtureProvider()
        r = p.fetch("San Jose", "SF", "2025-11-10T08:00:00-08:00")
        assert r.status_code == "OK"


class TestGoogleRoutesProvider:
    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            GoogleRoutesProvider(api_key="")

    @responses.activate
    def test_successful_response(self):
        responses.add(
            responses.POST,
            ROUTES_MATRIX_URL,
            json=[
                {
                    "duration": "2400s",
                    "distanceMeters": 78000,
                    "condition": "TRAFFIC_CONDITION_NORMAL",
                    "status": {"code": 0, "message": ""},
                }
            ],
            status=200,
        )
        p = GoogleRoutesProvider(api_key="test-key")
        r = p.fetch("Home", "Work", "2025-11-10T08:00:00-08:00")
        assert r.duration == "2400s"
        assert r.distance_meters == 78000
        assert r.condition == "TRAFFIC_CONDITION_NORMAL"
        assert r.status_code == "0"

    @responses.activate
    def test_http_error_returns_error_result(self):
        responses.add(
            responses.POST,
            ROUTES_MATRIX_URL,
            body="server explosion",
            status=500,
        )
        p = GoogleRoutesProvider(api_key="test-key")
        r = p.fetch("Home", "Work", "2025-11-10T08:00:00-08:00")
        assert r.status_code == "ERROR"
        assert r.duration is None
        assert "500" in (r.status_message or "")

    @responses.activate
    def test_unexpected_payload_returns_error(self):
        responses.add(
            responses.POST,
            ROUTES_MATRIX_URL,
            json={"oops": "not a list"},
            status=200,
        )
        p = GoogleRoutesProvider(api_key="test-key")
        r = p.fetch("Home", "Work", "2025-11-10T08:00:00-08:00")
        assert r.status_code == "ERROR"


class TestGetProvider:
    def test_defaults_to_fixture(self):
        p = get_provider(Settings(app_env="local", data_provider="fixture"))
        assert isinstance(p, FixtureProvider)

    def test_google_without_key_falls_back_to_fixture(self):
        p = get_provider(
            Settings(
                app_env="local",
                data_provider="google",
                google_maps_api_key=None,
            )
        )
        assert isinstance(p, FixtureProvider)

    def test_google_with_key(self):
        p = get_provider(
            Settings(
                app_env="local",
                data_provider="google",
                google_maps_api_key="abc",
            )
        )
        assert isinstance(p, GoogleRoutesProvider)


class TestProviderForUserEmail:
    """`provider_for_user_email` is the per-trip choke point that
    short-circuits Google Maps spend for App Store / Play Store
    reviewers. It must:

      * route reviewer emails to FixtureProvider regardless of
        global `data_provider`,
      * route non-reviewer emails through the global provider
        unchanged,
      * be case-insensitive on the email match,
      * handle missing emails (None / "") safely.
    """

    @staticmethod
    def _google_settings(reviewers: list[str] | None = None) -> Settings:
        return Settings(
            app_env="local",
            data_provider="google",
            google_maps_api_key="abc",
            review_account_emails=reviewers or [],
        )

    def test_reviewer_overrides_google(self):
        s = self._google_settings(["my.app.store.reviewer@gmail.com"])
        p = provider_for_user_email("my.app.store.reviewer@gmail.com", s)
        assert isinstance(p, FixtureProvider)

    def test_reviewer_match_is_case_insensitive(self):
        s = self._google_settings(["my.app.store.reviewer@gmail.com"])
        p = provider_for_user_email("My.App.Store.Reviewer@GMAIL.com", s)
        assert isinstance(p, FixtureProvider)

    def test_non_reviewer_uses_global_provider(self):
        s = self._google_settings(["my.app.store.reviewer@gmail.com"])
        p = provider_for_user_email("real.user@example.com", s)
        assert isinstance(p, GoogleRoutesProvider)

    def test_empty_reviewer_list_uses_global_provider(self):
        s = self._google_settings([])
        p = provider_for_user_email("anyone@example.com", s)
        assert isinstance(p, GoogleRoutesProvider)

    def test_none_email_falls_back_to_global_provider(self):
        s = self._google_settings(["my.app.store.reviewer@gmail.com"])
        p = provider_for_user_email(None, s)
        assert isinstance(p, GoogleRoutesProvider)

    def test_empty_email_falls_back_to_global_provider(self):
        s = self._google_settings(["my.app.store.reviewer@gmail.com"])
        p = provider_for_user_email("", s)
        assert isinstance(p, GoogleRoutesProvider)

    def test_local_fixture_provider_unchanged_for_non_reviewer(self):
        # If the operator is already on fixture, reviewer logic is
        # a no-op — but we still want a FixtureProvider back.
        s = Settings(
            app_env="local",
            data_provider="fixture",
            review_account_emails=["my.app.store.reviewer@gmail.com"],
        )
        p = provider_for_user_email("real.user@example.com", s)
        assert isinstance(p, FixtureProvider)
