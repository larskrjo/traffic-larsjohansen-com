"""
Commute-time providers.

A `CommuteProvider` returns the Google Routes Matrix style payload for a
single (origin, destination, departure_time) triple. Two implementations
ship today:

- `GoogleRoutesProvider`: real network call to Google's Routes Matrix API.
- `FixtureProvider`: deterministic synthetic data — no network, no key.

`get_provider()` picks the right one based on Settings.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import requests

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

ROUTES_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"


@dataclass
class CommuteResult:
    """Normalized response shape, independent of provider."""

    distance_meters: int | None
    duration: str | None
    condition: str | None
    status_code: str | None
    status_message: str | None


class CommuteProvider(Protocol):
    """Interface: return a CommuteResult for one origin→dest at one timestamp.

    `direction` is a provider hint ("outbound" / "return") so fixtures can
    produce realistic morning vs evening curves without sniffing addresses.
    Real providers (Google) ignore it.
    """

    def fetch(
        self,
        origin: str,
        destination: str,
        departure_rfc3339: str,
        direction: str | None = None,
    ) -> CommuteResult: ...


def _waypoint(address: str) -> dict:
    return {"waypoint": {"address": address}}


class GoogleRoutesProvider:
    """Calls Google's Routes Matrix API with TRAFFIC_AWARE routing."""

    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_key:
            raise ValueError("GoogleRoutesProvider requires a non-empty API key")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def fetch(
        self,
        origin: str,
        destination: str,
        departure_rfc3339: str,
        direction: str | None = None,
    ) -> CommuteResult:
        del direction  # unused — real Google call doesn't need the hint
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": "duration,distanceMeters,status,condition",
        }
        payload = {
            "origins": [_waypoint(origin)],
            "destinations": [_waypoint(destination)],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "departureTime": departure_rfc3339,
        }

        resp = requests.post(
            ROUTES_MATRIX_URL, headers=headers, json=payload, timeout=self._timeout
        )
        if resp.status_code != 200:
            return CommuteResult(
                distance_meters=None,
                duration=None,
                condition=None,
                status_code="ERROR",
                status_message=f"HTTP {resp.status_code}: {resp.text}",
            )

        data = resp.json()
        if not isinstance(data, list) or not data:
            return CommuteResult(
                distance_meters=None,
                duration=None,
                condition=None,
                status_code="ERROR",
                status_message=f"Unexpected response: {data}",
            )

        entry = data[0]
        status = entry.get("status", {}) or {}
        if isinstance(status, dict):
            raw_code = status.get("code")
            status_code = str(raw_code) if raw_code is not None else None
            raw_message = status.get("message")
            status_message = raw_message if raw_message else None
        else:
            status_code = str(status)
            status_message = None

        return CommuteResult(
            distance_meters=entry.get("distanceMeters"),
            duration=entry.get("duration") or None,
            condition=entry.get("condition") or None,
            status_code=status_code,
            status_message=status_message,
        )


class FixtureProvider:
    """Deterministic fake provider. Never touches the network.

    Models a rush-hour bell curve so the resulting heatmap looks realistic.
    """

    def __init__(self, base_distance_meters: int = 78000) -> None:
        self._base_distance = base_distance_meters

    def fetch(
        self,
        origin: str,
        destination: str,
        departure_rfc3339: str,
        direction: str | None = None,
    ) -> CommuteResult:
        ts = datetime.fromisoformat(departure_rfc3339)
        dir_hint = direction or ("outbound" if ts.hour < 13 else "return")
        minutes = self._synthetic_minutes(dir_hint, ts, origin, destination)
        return CommuteResult(
            distance_meters=self._base_distance,
            duration=f"{int(round(minutes * 60))}s",
            condition="TRAFFIC_CONDITION_NORMAL",
            status_code="OK",
            status_message=None,
        )

    @staticmethod
    def _synthetic_minutes(
        direction: str, ts: datetime, origin: str, destination: str
    ) -> float:
        hour = ts.hour + ts.minute / 60.0
        weekday_bump = {0: 0, 1: 2, 2: 3, 3: 4, 4: 6}.get(ts.weekday(), -10)
        # Origin/destination-dependent offset so different trips show
        # different baselines instead of the identical fixture curve.
        addr_bump = (abs(hash((origin, destination))) % 13) - 6
        outbound = direction in ("outbound", "H2W")
        if outbound:
            base, peak_hour, amp = 40.0, 8.25, 45.0
        else:
            base, peak_hour, amp = 45.0, 17.5, 50.0
        bell = math.exp(-((hour - peak_hour) ** 2) / (2 * 0.9**2))
        jitter = 2.5 * math.sin(ts.day * 0.7 + ts.hour * 0.3 + ts.minute * 0.05)
        return round(base + amp * bell + weekday_bump + addr_bump + jitter, 1)


def get_provider(settings: Settings | None = None) -> CommuteProvider:
    """Return the provider configured via Settings.

    Falls back from `google` to `fixture` (with a warning) if no API key.
    """
    settings = settings or get_settings()

    if settings.data_provider == "google":
        if not settings.google_maps_api_key:
            logger.warning(
                "DATA_PROVIDER=google but no GOOGLE_MAPS_API_KEY set; "
                "falling back to FixtureProvider"
            )
            return FixtureProvider()
        return GoogleRoutesProvider(settings.google_maps_api_key)

    return FixtureProvider()


def provider_for_user_email(
    email: str | None, settings: Settings | None = None
) -> CommuteProvider:
    """Pick the provider to use for a trip owned by `email`.

    Real users get `get_provider(settings)`. App Store / Play Store
    reviewer accounts (`settings.review_account_emails`) get the
    deterministic `FixtureProvider` regardless of `data_provider`, so
    the create-trip / delete-account / re-create-trip loop they run
    during review costs $0 in Google Maps spend.

    Lazy import of the dependency helper to avoid a config↔auth import
    cycle (auth.dependencies imports config; this module is reached
    from the job layer that auth has no business knowing about).
    """
    settings = settings or get_settings()
    # Lazy import: app.auth.dependencies → app.config, and this module
    # is on the cron / API call path, so an unconditional import would
    # create a cycle in some bootstraps.
    from app.auth.dependencies import is_review_account_email

    if is_review_account_email(email, settings):
        logger.info(
            "Routing trip for review account %s to FixtureProvider "
            "(no Google Maps spend).",
            email,
        )
        return FixtureProvider()
    return get_provider(settings)
