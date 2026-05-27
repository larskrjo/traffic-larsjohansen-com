"""
Typed application settings.

All environment-specific values live here. Local development works with the
built-in defaults; production overrides come from environment variables and
AWS Secrets Manager (loaded lazily on first access in prod).
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

AppEnv = Literal["local", "dev", "prod"]


class Settings(BaseSettings):
    """Top-level application settings.

    Values can be overridden by environment variables (case-insensitive).
    A `.env` file in the backend working directory is also respected.
    """

    app_env: AppEnv = "local"

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "Abcd1234"
    mysql_database: str = "time2leave"
    mysql_pool_size: int = 5

    google_maps_api_key: str | None = None
    data_provider: Literal["google", "fixture"] = "fixture"

    aws_secret_name: str = "MySecret"
    aws_region: str = "us-west-2"

    # Google OAuth / session.
    #
    # `google_oauth_client_id` is a *comma-separated* list of accepted
    # OAuth client IDs. The web SPA uses one ID; the iOS and Android
    # mobile clients each use their own. We accept a Google ID token
    # whose `aud` claim matches *any* of these (see
    # `Settings.google_oauth_client_ids`). Backwards compatible: a
    # plain `client-id` env value just yields a single-element list.
    google_oauth_client_id: str | None = None
    # Apple Sign In audience.
    #
    # Unlike Google OAuth, Apple Sign In does not require a client
    # secret on the backend — Apple identity tokens are JWTs we verify
    # with Apple's published JWKs. We just need to know *which* `aud`
    # claim to accept, which for native iOS sign-in is the iOS app's
    # bundle ID (e.g. `com.time2leave.app`).
    #
    # If you ever add Sign-in-with-Apple to the *web* (via the
    # https://appleid.apple.com/auth/authorize popup), you'd register
    # a separate Service ID with Apple and accept that `aud` too. For
    # now we only support the native iOS path, so this is a single
    # string. Defaults to the project's iOS bundle ID so local dev
    # works out of the box; prod can override via env or AWS Secrets
    # Manager (`apple_oauth_client_id` key).
    apple_oauth_client_id: str | None = "com.time2leave.app"
    session_secret: str = "dev-only-change-me"
    session_cookie_name: str = "tlh_session"
    session_ttl_hours: int = 24 * 7
    session_cookie_domain: str | None = None

    # Access control. `NoDecode` tells pydantic-settings not to try
    # JSON-parsing the raw env var; `_split_comma_separated` handles it.
    admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    auth_allowlist_bootstrap: Annotated[list[str], NoDecode] = Field(
        default_factory=list
    )
    # App Store / Play Store reviewer accounts. Every trip create or
    # address edit triggers a ~1,680-call Routes Matrix backfill
    # (~$16.80) plus a Geocoding pre-flight per address; reviewers
    # exercise create/delete flows repeatedly during review, which
    # would otherwise drain the Google Maps budget. Trips owned by
    # these emails get the deterministic `FixtureProvider` and a
    # no-op address validator instead — same UX (heatmap fills in,
    # delete works, re-create works), zero Google spend.
    #
    # Comma-separated env var (`REVIEW_ACCOUNT_EMAILS=foo@x,bar@y`).
    # Empty by default outside of prod.
    review_account_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=list
    )

    # Per-user and global trip quotas. Admins (emails in `admin_emails`)
    # get the higher `max_trips_per_admin` so the operator can keep a
    # personal-use trip alongside a "production smoke test" trip without
    # raising the cap for the whole user base.
    max_trips_per_user: int = 1
    max_trips_per_admin: int = 2
    max_trips_total: int = 10
    # Per-user rolling-7-day cap on "billed" trip mutations: trip creates
    # and trip patches that change addresses (or swap them). Each of those
    # operations triggers a Routes Matrix backfill (~840 calls / trip /
    # week), so this cap is the primary defense against a single user
    # draining the Google Maps budget by edit-spamming. Counted in
    # `trip_mutation_log`; surfaced in /api/v1/trips/quota; enforced
    # before Geocoding so we don't even pay for the pre-flight when a
    # user is over budget.
    max_trip_mutations_per_week: int = 1
    # Fail-closed ceiling on Routes Matrix calls the weekly Mon-01:00-PT
    # job may make.
    max_weekly_routes_calls: int = 150_000

    # Commute sampling window (local time).
    commute_window_start_hour: int = 6
    commute_window_end_hour: int = 21
    commute_interval_minutes: int = 15
    commute_days_per_week: int = 7
    commute_throttle_every: int = 50
    commute_throttle_seconds: float = 0.5

    # CORS origins allowed outside of prod. In prod we always allow exactly
    # https://time2leave.com and https://www.time2leave.com.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # Allow POST /api/v1/auth/dev-login outside of prod. Useful for local dev
    # and end-to-end tests so we don't need a real Google OAuth client.
    enable_dev_login: bool = True

    # Admin endpoints (manual run of the data-gathering job, etc.) are only
    # mounted when this is truthy AND app_env != "prod".
    enable_admin_api: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator(
        "admin_emails",
        "auth_allowlist_bootstrap",
        "review_account_emails",
        mode="before",
    )
    @classmethod
    def _split_email_lists(cls, v: object) -> object:
        """Allow ADMIN_EMAILS=foo@a,bar@b to parse into a lowercased list."""
        if isinstance(v, str):
            return [p.strip().lower() for p in v.split(",") if p.strip()]
        if isinstance(v, list):
            return [str(x).strip().lower() for x in v]
        return v

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Allow ALLOWED_ORIGINS=http://a,http://b to parse into a list.

        Origins keep their original casing (URLs are case-sensitive in path).
        """
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v]
        return v

    @property
    def google_oauth_client_ids(self) -> list[str]:
        """All accepted OAuth client IDs (web + iOS + Android), de-duplicated.

        Source of truth is the comma-separated `google_oauth_client_id`
        setting (env var or AWS Secrets Manager). Empty list when the
        backend is not yet configured for Google sign-in.
        """
        raw = self.google_oauth_client_id
        if not raw:
            return []
        seen: dict[str, None] = {}
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in seen:
                seen[cleaned] = None
        return list(seen.keys())


def _apply_legacy_env_aliases() -> None:
    """Accept the old DEVELOPMENT_MODE env var as an alias for APP_ENV.

    Removes a breaking change for anything still setting DEVELOPMENT_MODE
    (notably the prod docker-compose.yml before it's re-pulled).
    """
    if "APP_ENV" in os.environ:
        return
    legacy = os.environ.get("DEVELOPMENT_MODE")
    if legacy == "prod":
        os.environ["APP_ENV"] = "prod"
    elif legacy in {"dev", "local"}:
        os.environ["APP_ENV"] = legacy


# Quota envelope applied automatically when `app_env == "local"`.
#
# Production defaults are intentionally tiny (1 trip per user, 1
# mutation per week) because every cap-affecting action triggers a
# Routes Matrix backfill (~840 elements ≈ $8). Locally the data
# provider defaults to "fixture" so every backfill is free, which
# means the only real cost of bumping the caps is "the developer can
# now make 100 trips on their dev box without manually tweaking env
# vars". Each entry below is the (Settings attribute, dev-friendly
# value, env-var name); the env-var name is what the operator would
# set in `backend/.env` to override this overlay.
_LOCAL_DEV_QUOTA_OVERRIDES: tuple[tuple[str, int, str], ...] = (
    ("max_trips_per_user", 100, "MAX_TRIPS_PER_USER"),
    ("max_trips_per_admin", 100, "MAX_TRIPS_PER_ADMIN"),
    ("max_trips_total", 1_000, "MAX_TRIPS_TOTAL"),
    ("max_trip_mutations_per_week", 100, "MAX_TRIP_MUTATIONS_PER_WEEK"),
)


def _apply_local_dev_quotas(settings: Settings) -> None:
    """Bump per-user trip + mutation caps when running locally.

    Skipped if the operator has explicitly set the corresponding env
    var (so a contributor who *wants* to test prod-style caps locally
    can do `MAX_TRIPS_PER_USER=1 uvicorn …` without this overlay
    silently undoing it).

    Note that `.env`-file values are loaded by pydantic-settings
    *internally* and don't appear in `os.environ`, so they don't count
    as "explicit" here. If you want to opt out via .env, set the value
    in .env *and* export it; or just leave the overlay alone and
    benefit from the bumped caps that the dev workflow needs anyway.
    """
    if settings.app_env != "local":
        return
    for attr, dev_value, env_name in _LOCAL_DEV_QUOTA_OVERRIDES:
        if env_name in os.environ:
            continue
        setattr(settings, attr, dev_value)


def _load_from_aws_secrets_manager(settings: Settings) -> None:
    """Overlay MySQL + Google credentials from AWS Secrets Manager.

    Only invoked when app_env == "prod". Imported lazily so that local
    development does not require boto3 to reach AWS at import time.
    """
    import boto3
    from botocore.exceptions import ClientError

    session = boto3.session.Session()
    client = session.client(
        service_name="secretsmanager", region_name=settings.aws_region
    )
    try:
        resp = client.get_secret_value(SecretId=settings.aws_secret_name)
    except ClientError:
        logger.exception(
            "Failed to load AWS secret '%s' in region %s",
            settings.aws_secret_name,
            settings.aws_region,
        )
        raise

    payload: dict[str, str] = json.loads(resp["SecretString"])
    if "mysql_user" in payload:
        settings.mysql_user = payload["mysql_user"]
    if "mysql_password" in payload:
        settings.mysql_password = payload["mysql_password"]
    if "google_maps_api_key" in payload:
        settings.google_maps_api_key = payload["google_maps_api_key"]
        if settings.data_provider == "fixture":
            settings.data_provider = "google"
    if "google_oauth_client_id" in payload:
        settings.google_oauth_client_id = payload["google_oauth_client_id"]
    if "apple_oauth_client_id" in payload:
        settings.apple_oauth_client_id = payload["apple_oauth_client_id"]
    if "session_secret" in payload:
        settings.session_secret = payload["session_secret"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide singleton Settings instance.

    Resolution order:
      1. Start from defaults.
      2. Apply env vars (including any `.env` file).
      3. In prod, overlay AWS Secrets Manager values.
    """
    _apply_legacy_env_aliases()
    settings = Settings()

    if settings.app_env == "prod":
        _load_from_aws_secrets_manager(settings)
        settings.enable_dev_login = False
    else:
        logger.info(
            "Running in %s mode; skipping AWS Secrets Manager and using env/defaults",
            settings.app_env,
        )
        _apply_local_dev_quotas(settings)

    return settings


def reset_settings_cache() -> None:
    """Clear the cached Settings. Intended for tests."""
    get_settings.cache_clear()
