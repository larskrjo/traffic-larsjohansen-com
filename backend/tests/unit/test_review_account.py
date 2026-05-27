"""Unit tests for the App Store / Play Store reviewer-account
short-circuit helpers.

The single source of truth for "is this user a reviewer?" is
`app.auth.dependencies.is_review_account_email` (and its `User`-typed
wrapper `is_review_account`). These tests pin its behavior because
multiple cost-control paths fan out from it:

  * `provider_for_user_email` swaps in `FixtureProvider` when this
    helper returns True (test in `test_providers.py`).
  * `trips_api._address_validator_for` swaps in `NullAddressValidator`
    when this helper returns True (test in `test_trips_api.py`).
  * `data_gathering._filter_out_review_account_trips` drops trips
    from the weekly cron when this helper returns True for the
    owner.

A regression in this helper would silently re-enable real Google
Maps spend for review accounts, which is exactly the bug class this
feature exists to prevent — so the matrix here is deliberately wide.
"""

from __future__ import annotations

from app.auth.dependencies import is_review_account, is_review_account_email
from app.config import Settings
from app.services.users import User


def _settings(emails: list[str] | None = None) -> Settings:
    return Settings(review_account_emails=emails or [])


def _user(email: str) -> User:
    return User(
        id=1,
        google_sub="g-1",
        apple_sub=None,
        email=email,
        name="Test",
        picture_url=None,
    )


class TestIsReviewAccountEmail:
    def test_matches_exact_email(self):
        s = _settings(["my.app.store.reviewer@gmail.com"])
        assert is_review_account_email("my.app.store.reviewer@gmail.com", s)

    def test_match_is_case_insensitive(self):
        s = _settings(["my.app.store.reviewer@gmail.com"])
        assert is_review_account_email("My.App.Store.Reviewer@GMAIL.com", s)

    def test_no_match_for_random_email(self):
        s = _settings(["my.app.store.reviewer@gmail.com"])
        assert not is_review_account_email("real.user@example.com", s)

    def test_empty_list_never_matches(self):
        assert not is_review_account_email("anyone@anywhere.com", _settings([]))

    def test_none_email_is_false(self):
        s = _settings(["my.app.store.reviewer@gmail.com"])
        assert not is_review_account_email(None, s)

    def test_empty_email_is_false(self):
        s = _settings(["my.app.store.reviewer@gmail.com"])
        assert not is_review_account_email("", s)

    def test_partial_email_does_not_match(self):
        """No substring matching — the helper compares full addresses
        so a colliding prefix or suffix can't accidentally elevate a
        real user to reviewer status."""
        s = _settings(["reviewer@gmail.com"])
        assert not is_review_account_email("other.reviewer@gmail.com", s)
        assert not is_review_account_email("reviewer@gmail.com.evil", s)

    def test_multiple_reviewers(self):
        """Lists with multiple entries (Apple + Google reviewers)
        all resolve correctly."""
        s = _settings(["apple@x.com", "google@y.com"])
        assert is_review_account_email("apple@x.com", s)
        assert is_review_account_email("google@y.com", s)
        assert not is_review_account_email("other@z.com", s)


class TestIsReviewAccount:
    def test_user_wrapper_routes_through_email(self):
        s = _settings(["reviewer@gmail.com"])
        assert is_review_account(_user("reviewer@gmail.com"), s)
        assert not is_review_account(_user("real@gmail.com"), s)
