"""Route-level tests for `/api/v1/trips/*`.

Services are monkey-patched with an in-memory fake so we get real
HTTP wiring coverage without a DB. `get_current_user` is overridden so
we don't need to issue session cookies.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.services import trips as trips_service
from app.services.trips import Trip, TripNotFoundError, TripQuotaExceededError
from app.services.users import User


@pytest.fixture
def logged_in_user() -> User:
    return User(
        id=99,
        google_sub="sub-99",
        apple_sub=None,
        email="user@example.com",
        name="Test User",
        picture_url=None,
    )


def _make_trip(
    *,
    id: int,
    user_id: int = 99,
    name: str | None = "x",
    origin_address: str = "A",
    destination_address: str = "B",
    created_at: datetime | None = None,
    slug: str | None = None,
) -> Trip:
    """Build a Trip for fixtures with a defaulted, predictable slug.

    Slug defaults to `slug-{id:05d}` so tests can address the trip by
    its public identifier without hard-coding random hex everywhere
    while still exercising the slug-based lookup paths end-to-end.
    """
    return Trip(
        id=id,
        slug=slug or f"slug-{id:05d}",
        user_id=user_id,
        name=name,
        origin_address=origin_address,
        destination_address=destination_address,
        created_at=created_at,
    )


@pytest.fixture
def fake_trips_store() -> dict[int, Trip]:
    return {}


@pytest.fixture
def fake_mutation_log() -> list[dict]:
    """Fake `trip_mutation_log` rows. Tests can inspect/seed this."""
    return []


@pytest.fixture
def fake_backfill_kickoffs() -> list[tuple[int, str]]:
    """Captured `(trip_id, week_start.isoformat())` from background backfills.

    Lets tests assert that a trip create/edit fires backfills for both
    the current and next week (and that ?week=next on backfill-status
    does NOT enqueue anything).
    """
    return []


@pytest.fixture
def fake_next_week_available() -> dict[str, bool]:
    """Mutable container so tests can flip `is_week_fully_populated`.

    Default is False (matches a fresh trip); tests that want to verify
    the toggle-visible path set `state["value"] = True` before hitting
    the heatmap endpoint.
    """
    return {"value": False}


@pytest.fixture
def patched_app(
    monkeypatch: pytest.MonkeyPatch,
    logged_in_user: User,
    fake_trips_store: dict[int, Trip],
    fake_mutation_log: list[dict],
    fake_backfill_kickoffs: list[tuple[int, str]],
    fake_next_week_available: dict[str, bool],
) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "local")
    from app.config import reset_settings_cache

    reset_settings_cache()

    def fake_list(user_id: int) -> list[Trip]:
        return [t for t in fake_trips_store.values() if t.user_id == user_id]

    def fake_get_by_slug(*, slug: str, user_id: int) -> Trip:
        for trip in fake_trips_store.values():
            if trip.slug == slug and trip.user_id == user_id:
                return trip
        raise TripNotFoundError("not found")

    next_id = {"value": 1}

    def fake_create(
        *, user_id, name, origin_address, destination_address, per_user_cap, total_cap
    ):
        owned = [t for t in fake_trips_store.values() if t.user_id == user_id]
        if len(owned) >= per_user_cap:
            raise TripQuotaExceededError("per-user")
        if len(fake_trips_store) >= total_cap:
            raise TripQuotaExceededError("total")
        new_id = next_id["value"]
        trip = _make_trip(
            id=new_id,
            user_id=user_id,
            name=name,
            origin_address=origin_address,
            destination_address=destination_address,
            created_at=datetime(2025, 11, 1, 12, 0),
        )
        next_id["value"] += 1
        fake_trips_store[trip.id] = trip
        return trip

    def fake_soft_delete(*, trip_id: int, user_id: int) -> None:
        trip = fake_trips_store.get(trip_id)
        if not trip or trip.user_id != user_id:
            raise TripNotFoundError("not found")
        del fake_trips_store[trip_id]

    from app.services.trips import _UNSET

    def fake_update(
        *,
        trip_id: int,
        user_id: int,
        name=_UNSET,
        origin_address=None,
        destination_address=None,
    ):
        trip = fake_trips_store.get(trip_id)
        if not trip or trip.user_id != user_id:
            raise TripNotFoundError("not found")
        new_name = trip.name if name is _UNSET else name
        new_origin = (
            origin_address.strip()
            if origin_address is not None
            else trip.origin_address
        )
        new_destination = (
            destination_address.strip()
            if destination_address is not None
            else trip.destination_address
        )
        if new_origin.lower() == new_destination.lower():
            raise ValueError("same address")
        addresses_changed = (
            new_origin != trip.origin_address
            or new_destination != trip.destination_address
        )
        updated = _make_trip(
            id=trip.id,
            slug=trip.slug,
            user_id=trip.user_id,
            name=new_name,
            origin_address=new_origin,
            destination_address=new_destination,
            created_at=trip.created_at,
        )
        fake_trips_store[trip_id] = updated
        return updated, addresses_changed

    def fake_count(user_id: int) -> int:
        return len([t for t in fake_trips_store.values() if t.user_id == user_id])

    def fake_heatmap(trip_id: int, week_start):  # noqa: ARG001
        return {
            "outbound": {"Mon": {"06:00": 42.0}},
            "return": {},
            "week_start_date": week_start.isoformat(),
            "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        }

    def fake_sample_status(trip_id: int, week_start):  # noqa: ARG001
        return {"total": 840, "ready": 210}

    import app.api.trips_api as trips_api_mod

    # In-memory `trip_mutation_log` so we can test the rolling-7-day cap
    # without a DB. The fakes preserve the real service's invariants:
    # `assert_mutation_quota` raises when at-or-over the cap, and
    # `record_mutation` appends a row that future calls count against.
    from app.services.trip_mutations import (
        MutationQuota,
        TripMutationQuotaExceededError,
    )

    def fake_assert_quota(user_id, settings):  # noqa: ARG001
        used = sum(1 for r in fake_mutation_log if r["user_id"] == user_id)
        limit = settings.max_trip_mutations_per_week
        if used >= limit:
            raise TripMutationQuotaExceededError(
                used=used, limit=limit, retry_after_seconds=3600
            )

    def fake_mutation_quota(user_id, settings):
        used = sum(1 for r in fake_mutation_log if r["user_id"] == user_id)
        return MutationQuota(
            used=used,
            limit=settings.max_trip_mutations_per_week,
            oldest_age_seconds=None if used == 0 else 60,
        )

    def fake_record_mutation(*, user_id, trip_id, kind):
        fake_mutation_log.append(
            {"user_id": user_id, "trip_id": trip_id, "kind": kind}
        )

    monkeypatch.setattr(trips_api_mod, "list_trips_for_user", fake_list)
    monkeypatch.setattr(
        trips_api_mod, "get_trip_for_user_by_slug", fake_get_by_slug
    )
    monkeypatch.setattr(trips_api_mod, "create_trip", fake_create)
    monkeypatch.setattr(trips_api_mod, "soft_delete_trip", fake_soft_delete)
    monkeypatch.setattr(trips_api_mod, "update_trip", fake_update)
    monkeypatch.setattr(trips_api_mod, "count_trips_for_user", fake_count)
    monkeypatch.setattr(trips_api_mod, "get_heatmap_for_trip", fake_heatmap)
    monkeypatch.setattr(trips_api_mod, "sample_status_for_trip", fake_sample_status)
    monkeypatch.setattr(trips_api_mod, "assert_mutation_quota", fake_assert_quota)
    monkeypatch.setattr(
        trips_api_mod, "mutation_quota_for_user", fake_mutation_quota
    )
    monkeypatch.setattr(trips_api_mod, "record_mutation", fake_record_mutation)

    # Prevent the background backfill from touching anything real, and
    # capture every (trip_id, week_start) pair that gets enqueued so
    # tests can assert the dual-week behavior.
    def fake_kickoff(trip_id: int, week_start) -> None:
        fake_backfill_kickoffs.append((trip_id, week_start.isoformat()))

    monkeypatch.setattr(trips_api_mod, "_kickoff_backfill", fake_kickoff)

    # `is_week_fully_populated` lives in `services.trips` and is imported
    # into `trips_api`. We patch the imported reference so the heatmap
    # endpoint sees the value tests set, without touching the DB.
    monkeypatch.setattr(
        trips_api_mod,
        "is_week_fully_populated",
        lambda _trip_id, _week_start: fake_next_week_available["value"],
    )

    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: logged_in_user
    with TestClient(app) as c:
        yield c


def test_requires_auth_without_override() -> None:
    """Without the dependency override, every trips route is 401."""
    from app.config import reset_settings_cache
    from app.main import create_app

    reset_settings_cache()
    app = create_app()
    with TestClient(app) as c:
        assert c.get("/api/v1/trips").status_code == 401
        assert c.post("/api/v1/trips", json={}).status_code == 401


def test_list_trips_empty(patched_app: TestClient) -> None:
    r = patched_app.get("/api/v1/trips")
    assert r.status_code == 200
    assert r.json() == []


def test_create_trip_returns_backfill_status(patched_app: TestClient) -> None:
    r = patched_app.post(
        "/api/v1/trips",
        json={
            "name": "Commute",
            "origin_address": "A St",
            "destination_address": "B Ave",
        },
    )
    assert r.status_code == 201
    body = r.json()
    # `id` is now the public 10-hex slug (string), not the int PK.
    # `_make_trip` defaults the slug from the int id used by the
    # in-memory store (`slug-00001` for the first inserted trip).
    assert body["id"] == "slug-00001"
    assert body["name"] == "Commute"
    assert body["backfill"] == {
        "total": 840,
        "ready": 210,
        "percent_complete": 25.0,
    }


def test_create_trip_rejects_same_origin_destination(patched_app: TestClient) -> None:
    r = patched_app.post(
        "/api/v1/trips",
        json={"origin_address": "same", "destination_address": "same"},
    )
    assert r.status_code == 400


def test_create_trip_enforces_per_user_cap(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pre-fill exactly the configured per-user limit so adding one more
    # is the *first* request to breach the cap. Reads the limit from
    # settings instead of hard-coding it so this test stays correct
    # whether the default is 1, 3, or anything else.
    from app.config import get_settings

    limit = get_settings().max_trips_per_user
    for i in range(limit):
        fake_trips_store[i + 1] = _make_trip(
            id=i + 1,
            user_id=99,
            name=f"T{i}",
            origin_address="a",
            destination_address="b",
            created_at=None,
        )

    r = patched_app.post(
        "/api/v1/trips",
        json={
            "origin_address": "100 Main St",
            "destination_address": "200 Oak Ave",
        },
    )
    assert r.status_code == 409


def test_admin_user_gets_elevated_per_user_trip_cap(
    patched_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admins (emails in ADMIN_EMAILS) get `max_trips_per_admin`, not `_per_user`.

    Mutation cap is bumped here so the post loop isn't blocked by the
    weekly mutation guard before we can test the trip-count guard.
    """
    monkeypatch.setenv("ADMIN_EMAILS", "user@example.com")  # matches fixture user
    monkeypatch.setenv("MAX_TRIPS_PER_USER", "1")
    monkeypatch.setenv("MAX_TRIPS_PER_ADMIN", "2")
    monkeypatch.setenv("MAX_TRIP_MUTATIONS_PER_WEEK", "5")
    from app.config import reset_settings_cache

    reset_settings_cache()

    r = patched_app.get("/api/v1/trips/quota")
    assert r.status_code == 200
    assert r.json()["limit"] == 2

    for i in range(2):
        r = patched_app.post(
            "/api/v1/trips",
            json={
                "origin_address": f"{100 + i} Main St",
                "destination_address": f"{200 + i} Oak Ave",
            },
        )
        assert r.status_code == 201, r.text

    r = patched_app.post(
        "/api/v1/trips",
        json={
            "origin_address": "999 Nope St",
            "destination_address": "888 Stop Ave",
        },
    )
    assert r.status_code == 409


def test_non_admin_user_keeps_lower_per_user_trip_cap(
    patched_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check the inverse: a non-admin sees `max_trips_per_user`."""
    monkeypatch.setenv("ADMIN_EMAILS", "someone-else@example.com")
    monkeypatch.setenv("MAX_TRIPS_PER_USER", "1")
    monkeypatch.setenv("MAX_TRIPS_PER_ADMIN", "2")
    from app.config import reset_settings_cache

    reset_settings_cache()

    r = patched_app.get("/api/v1/trips/quota")
    assert r.status_code == 200
    assert r.json()["limit"] == 1


def test_get_trip_unknown_id_404s(patched_app: TestClient) -> None:
    r = patched_app.get("/api/v1/trips/12345")
    assert r.status_code == 404


def test_delete_trip_removes_it(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )
    r = patched_app.delete("/api/v1/trips/slug-00001")
    assert r.status_code == 204
    assert 1 not in fake_trips_store


def test_heatmap_returns_expected_shape(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )
    r = patched_app.get("/api/v1/trips/slug-00001/heatmap")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"outbound", "return", "week_start_date", "weekdays"}
    assert body["outbound"] == {"Mon": {"06:00": 42.0}}


def test_quota_endpoint_reports_used_and_limit(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )
    r = patched_app.get("/api/v1/trips/quota")
    assert r.status_code == 200
    body = r.json()
    assert body["used"] == 1
    assert body["limit"] >= 1


def test_patch_trip_renames_without_touching_addresses(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="old",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    r = patched_app.patch("/api/v1/trips/slug-00001", json={"name": "renamed"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "renamed"
    assert body["origin_address"] == "100 Main St"


def test_patch_trip_swap_flips_origin_and_destination(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    r = patched_app.patch("/api/v1/trips/slug-00001", json={"swap_addresses": True})
    assert r.status_code == 200
    body = r.json()
    assert body["origin_address"] == "200 Oak Ave"
    assert body["destination_address"] == "100 Main St"


def test_patch_trip_clear_name_sets_it_to_null(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="had a name",
        origin_address="a st",
        destination_address="b st",
        created_at=None,
    )
    r = patched_app.patch("/api/v1/trips/slug-00001", json={"clear_name": True})
    assert r.status_code == 200
    assert r.json()["name"] is None


def test_patch_trip_rejects_same_origin_destination(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    r = patched_app.patch(
        "/api/v1/trips/slug-00001",
        json={"origin_address": "same addr", "destination_address": "same addr"},
    )
    assert r.status_code == 400


def test_current_week_start_is_monday() -> None:
    # Thursday 2025-11-13 → Monday 2025-11-10
    from datetime import date as d

    assert trips_service.current_week_start(d(2025, 11, 13)) == d(2025, 11, 10)


class _StubValidator:
    """Test double that rejects a preconfigured set of addresses.

    Lets us exercise the prod validation path without mocking the real
    Google Geocoding HTTP call at the route layer.
    """

    def __init__(self, invalid: set[str]) -> None:
        self._invalid = invalid
        self.calls: list[str] = []

    def validate(self, address: str):
        from app.services.address_validation import AddressValidation

        self.calls.append(address)
        if address in self._invalid:
            return AddressValidation(
                is_valid=False, reason=f"fake: rejected {address!r}"
            )
        return AddressValidation(is_valid=True, canonical=address)


def _install_validator(
    monkeypatch: pytest.MonkeyPatch, invalid: set[str]
) -> _StubValidator:
    stub = _StubValidator(invalid=invalid)
    import app.api.trips_api as trips_api_mod

    monkeypatch.setattr(
        trips_api_mod, "get_address_validator", lambda _settings=None: stub
    )
    return stub


def test_create_trip_rejects_invalid_address(
    patched_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _install_validator(monkeypatch, invalid={"bogus origin"})
    r = patched_app.post(
        "/api/v1/trips",
        json={
            "name": "Commute",
            "origin_address": "bogus origin",
            "destination_address": "200 Oak Ave",
        },
    )
    assert r.status_code == 400
    assert "bogus origin" in r.json()["detail"]
    # The origin should short-circuit before the destination is checked.
    assert stub.calls == ["bogus origin"]


def test_create_trip_accepts_valid_addresses_via_validator(
    patched_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _install_validator(monkeypatch, invalid=set())
    r = patched_app.post(
        "/api/v1/trips",
        json={
            "name": "Commute",
            "origin_address": "100 Main St",
            "destination_address": "200 Oak Ave",
        },
    )
    assert r.status_code == 201
    assert stub.calls == ["100 Main St", "200 Oak Ave"]


def test_patch_trip_validates_only_changed_origin(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    stub = _install_validator(monkeypatch, invalid={"junk"})
    r = patched_app.patch(
        "/api/v1/trips/slug-00001",
        json={"origin_address": "junk"},
    )
    assert r.status_code == 400
    # Destination wasn't in the request, so we shouldn't waste a
    # Geocoding call on it.
    assert stub.calls == ["junk"]


class TestReviewAccountCostGuards:
    """Cost-control bypasses for App Store / Play Store reviewer accounts.

    Three surfaces fan out from `is_review_account`:

      1. Geocoding pre-flight — swapped to NullAddressValidator so the
         reviewer can type test addresses ("home", "1234") without
         "couldn't find that on Google Maps" rejections.
      2. Per-user trip cap — bumped to an effectively-unlimited value
         (`_REVIEWER_UNLIMITED_CAP`) so the create/delete loop the
         test plan exercises doesn't bump into the prod 1-trip cap.
      3. Rolling-7-day mutation quota — bypassed entirely so the
         reviewer can run the create / edit / swap / delete cycle
         repeatedly in one session.

    All three are gated by the same email check so a single env-var
    rotation (`REVIEW_ACCOUNT_EMAILS`) toggles every bypass together.
    """

    @pytest.fixture
    def reviewer_user(self) -> User:
        return User(
            id=99,
            google_sub="sub-reviewer",
            apple_sub=None,
            email="my.app.store.reviewer@gmail.com",
            name="App Store Reviewer",
            picture_url=None,
        )

    @pytest.fixture
    def reviewer_patched_app(
        self,
        monkeypatch: pytest.MonkeyPatch,
        reviewer_user: User,
        fake_trips_store: dict[int, Trip],
        fake_mutation_log: list[dict],
        fake_backfill_kickoffs: list[tuple[int, str]],
        fake_next_week_available: dict[str, bool],
    ) -> Iterator[TestClient]:
        # Set the env BEFORE the in-fixture `reset_settings_cache()`
        # so the new Settings instance sees the reviewer email.
        monkeypatch.setenv(
            "REVIEW_ACCOUNT_EMAILS", "my.app.store.reviewer@gmail.com"
        )
        # Reuse the existing patched_app machinery by recursively
        # asking pytest for it, with our overridden `logged_in_user`
        # injected via dependency_overrides below.
        from app.config import reset_settings_cache
        from app.main import create_app

        reset_settings_cache()

        # Inline the same fakes the main `patched_app` uses. We
        # deliberately don't refactor it into a helper here because the
        # surface is small enough to duplicate and keeping fixture-vs-
        # test responsibilities legible matters more than DRY.
        def fake_list(user_id: int) -> list[Trip]:
            return [t for t in fake_trips_store.values() if t.user_id == user_id]

        def fake_get_by_slug(*, slug: str, user_id: int) -> Trip:
            for trip in fake_trips_store.values():
                if trip.slug == slug and trip.user_id == user_id:
                    return trip
            raise TripNotFoundError("not found")

        next_id = {"value": 1}

        def fake_create(
            *,
            user_id,
            name,
            origin_address,
            destination_address,
            per_user_cap,
            total_cap,
        ):
            owned = [t for t in fake_trips_store.values() if t.user_id == user_id]
            if len(owned) >= per_user_cap:
                raise TripQuotaExceededError("per-user")
            if len(fake_trips_store) >= total_cap:
                raise TripQuotaExceededError("total")
            new_id = next_id["value"]
            trip = _make_trip(
                id=new_id,
                user_id=user_id,
                name=name,
                origin_address=origin_address,
                destination_address=destination_address,
                created_at=datetime(2025, 11, 1, 12, 0),
            )
            next_id["value"] += 1
            fake_trips_store[trip.id] = trip
            return trip

        from app.services.trips import _UNSET

        def fake_update(
            *,
            trip_id: int,
            user_id: int,
            name=_UNSET,
            origin_address=None,
            destination_address=None,
        ):
            trip = fake_trips_store.get(trip_id)
            if not trip or trip.user_id != user_id:
                raise TripNotFoundError("not found")
            new_name = trip.name if name is _UNSET else name
            new_origin = (
                origin_address.strip()
                if origin_address is not None
                else trip.origin_address
            )
            new_destination = (
                destination_address.strip()
                if destination_address is not None
                else trip.destination_address
            )
            if new_origin.lower() == new_destination.lower():
                raise ValueError("same address")
            addresses_changed = (
                new_origin != trip.origin_address
                or new_destination != trip.destination_address
            )
            updated = _make_trip(
                id=trip.id,
                slug=trip.slug,
                user_id=trip.user_id,
                name=new_name,
                origin_address=new_origin,
                destination_address=new_destination,
                created_at=trip.created_at,
            )
            fake_trips_store[trip_id] = updated
            return updated, addresses_changed

        def fake_count(user_id: int) -> int:
            return len(
                [t for t in fake_trips_store.values() if t.user_id == user_id]
            )

        from app.services.trip_mutations import (
            MutationQuota,
            TripMutationQuotaExceededError,
        )

        # Pin the per-user prod cap of 1 so an "unlimited" assertion
        # can't accidentally pass by being below the dev overlay of 100.
        # The `_apply_local_dev_quotas` overlay only kicks in when the
        # env var is unset; setting it explicitly opts out.
        monkeypatch.setenv("MAX_TRIPS_PER_USER", "1")
        monkeypatch.setenv("MAX_TRIP_MUTATIONS_PER_WEEK", "1")

        # Counters so reviewer-bypass tests can assert that the real
        # quota check was *not* even consulted for a reviewer.
        assert_quota_calls: list[int] = []
        record_mutation_calls: list[dict] = []

        def fake_assert_quota(user_id, settings):  # noqa: ARG001
            assert_quota_calls.append(user_id)
            used = sum(1 for r in fake_mutation_log if r["user_id"] == user_id)
            limit = settings.max_trip_mutations_per_week
            if used >= limit:
                raise TripMutationQuotaExceededError(
                    used=used, limit=limit, retry_after_seconds=3600
                )

        def fake_mutation_quota(user_id, settings):
            used = sum(1 for r in fake_mutation_log if r["user_id"] == user_id)
            return MutationQuota(
                used=used,
                limit=settings.max_trip_mutations_per_week,
                oldest_age_seconds=None if used == 0 else 60,
            )

        def fake_record_mutation(*, user_id, trip_id, kind):
            record_mutation_calls.append(
                {"user_id": user_id, "trip_id": trip_id, "kind": kind}
            )
            fake_mutation_log.append(
                {"user_id": user_id, "trip_id": trip_id, "kind": kind}
            )

        def fake_sample_status(trip_id, week_start):  # noqa: ARG001
            return {"total": 840, "ready": 210}

        def fake_kickoff(trip_id: int, week_start) -> None:
            fake_backfill_kickoffs.append((trip_id, week_start.isoformat()))

        # Expose the counters on the fixture object so tests can pull
        # them from the TestClient (`c._reviewer_assert_quota_calls`).
        # Slightly unusual but keeps the test signatures clean — adding
        # a separate `reviewer_quota_counters` fixture for two ints
        # would be more ceremony than the data warrants.
        self._counters = {
            "assert_quota": assert_quota_calls,
            "record_mutation": record_mutation_calls,
        }

        import app.api.trips_api as trips_api_mod

        monkeypatch.setattr(trips_api_mod, "list_trips_for_user", fake_list)
        monkeypatch.setattr(
            trips_api_mod, "get_trip_for_user_by_slug", fake_get_by_slug
        )
        monkeypatch.setattr(trips_api_mod, "create_trip", fake_create)
        monkeypatch.setattr(trips_api_mod, "update_trip", fake_update)
        monkeypatch.setattr(trips_api_mod, "count_trips_for_user", fake_count)
        monkeypatch.setattr(
            trips_api_mod, "assert_mutation_quota", fake_assert_quota
        )
        monkeypatch.setattr(
            trips_api_mod, "mutation_quota_for_user", fake_mutation_quota
        )
        monkeypatch.setattr(trips_api_mod, "record_mutation", fake_record_mutation)
        monkeypatch.setattr(
            trips_api_mod, "sample_status_for_trip", fake_sample_status
        )
        monkeypatch.setattr(trips_api_mod, "_kickoff_backfill", fake_kickoff)

        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: reviewer_user
        with TestClient(app) as c:
            yield c

    def test_reviewer_bypasses_geocoding_validator(
        self,
        reviewer_patched_app: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Install a validator that rejects every address. The reviewer
        path must bypass it entirely and create the trip anyway."""
        # `invalid` includes both addresses → if the stub is ever
        # consulted, the request fails. The point of this test is to
        # prove it's NOT consulted for a reviewer.
        stub = _install_validator(
            monkeypatch, invalid={"reviewer origin", "reviewer destination"}
        )
        r = reviewer_patched_app.post(
            "/api/v1/trips",
            json={
                "name": "Reviewer Commute",
                "origin_address": "reviewer origin",
                "destination_address": "reviewer destination",
            },
        )
        assert r.status_code == 201, r.text
        assert stub.calls == [], (
            "GoogleGeocodingValidator stub was consulted for a reviewer "
            "account — the reviewer path should swap in NullAddressValidator "
            "before reaching get_address_validator at all."
        )

    def test_non_reviewer_still_hits_validator(
        self,
        patched_app: TestClient,  # uses the normal `logged_in_user`
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Negative control: a normal user's create still pays the
        Geocoding pre-flight (and gets rejected by a bad address).

        Runs against the original `patched_app` (where `logged_in_user`
        is `user@example.com`, not a reviewer) to prove the swap is
        scoped to the reviewer email list and not a global no-op.
        """
        stub = _install_validator(monkeypatch, invalid={"reviewer origin"})
        r = patched_app.post(
            "/api/v1/trips",
            json={
                "name": "Real Commute",
                "origin_address": "reviewer origin",
                "destination_address": "200 Oak Ave",
            },
        )
        assert r.status_code == 400
        assert stub.calls == ["reviewer origin"]

    def test_reviewer_quota_endpoint_reports_unlimited_caps(
        self, reviewer_patched_app: TestClient
    ) -> None:
        """`/api/v1/trips/quota` should surface the bumped caps so the
        SPA doesn't paint a "1 / 1 weekly edits" badge that would scare
        the reviewer into thinking they're locked out."""
        from app.api.trips_api import _REVIEWER_UNLIMITED_CAP

        r = reviewer_patched_app.get("/api/v1/trips/quota")
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == _REVIEWER_UNLIMITED_CAP
        assert body["mutations_limit"] == _REVIEWER_UNLIMITED_CAP

    def test_non_reviewer_quota_endpoint_unchanged(
        self, patched_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative control: a normal user's /quota still reports the
        real prod caps from settings, not the reviewer-unlimited value.
        Pins the env vars explicitly so the local-dev overlay doesn't
        balloon them to 100."""
        monkeypatch.setenv("MAX_TRIPS_PER_USER", "1")
        monkeypatch.setenv("MAX_TRIP_MUTATIONS_PER_WEEK", "1")
        from app.config import reset_settings_cache

        reset_settings_cache()

        r = patched_app.get("/api/v1/trips/quota")
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == 1
        assert body["mutations_limit"] == 1

    def test_reviewer_can_create_many_trips_in_a_row(
        self, reviewer_patched_app: TestClient
    ) -> None:
        """The reviewer test plan exercises the create / delete cycle
        repeatedly. With `MAX_TRIPS_PER_USER=1` pinned in the fixture
        and no review-account bypass, this would 409 on the second
        request — proving the bypass actually moves the cap upward."""
        for i in range(5):
            r = reviewer_patched_app.post(
                "/api/v1/trips",
                json={
                    "name": f"Trip {i}",
                    "origin_address": f"origin-{i}",
                    "destination_address": f"destination-{i}",
                },
            )
            assert r.status_code == 201, (
                f"create #{i + 1} returned {r.status_code}: {r.text}"
            )

    def test_reviewer_create_skips_mutation_quota_check_entirely(
        self, reviewer_patched_app: TestClient
    ) -> None:
        """The bypass is short-circuit — the route doesn't even ask
        `assert_mutation_quota`, so a quota service outage (or a bug
        that 500s the quota path) can't accidentally lock a reviewer
        out mid-session."""
        for i in range(3):
            r = reviewer_patched_app.post(
                "/api/v1/trips",
                json={
                    "origin_address": f"o-{i}",
                    "destination_address": f"d-{i}",
                },
            )
            assert r.status_code == 201, r.text

        assert self._counters["assert_quota"] == [], (
            "assert_mutation_quota was called for a reviewer — "
            "the bypass should short-circuit before reaching it."
        )

    def test_reviewer_can_edit_addresses_unlimited(
        self,
        reviewer_patched_app: TestClient,
        fake_trips_store: dict[int, Trip],
    ) -> None:
        """Reviewer can run an unbounded number of address-changing
        PATCHes. With `MAX_TRIP_MUTATIONS_PER_WEEK=1`, a normal user
        would hit a 429 immediately after the first edit."""
        fake_trips_store[1] = _make_trip(
            id=1,
            user_id=99,  # matches `reviewer_user.id`
            name="x",
            origin_address="A",
            destination_address="B",
            created_at=None,
        )

        for i in range(5):
            r = reviewer_patched_app.patch(
                "/api/v1/trips/slug-00001",
                json={"origin_address": f"new-origin-{i}"},
            )
            assert r.status_code == 200, (
                f"edit #{i + 1} returned {r.status_code}: {r.text}"
            )

        assert self._counters["assert_quota"] == [], (
            "assert_mutation_quota was called during a reviewer edit — "
            "the bypass should short-circuit before reaching it."
        )

    def test_non_reviewer_still_hits_mutation_quota(
        self, patched_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative control: a regular user STILL hits 429 on the
        second create with `MAX_TRIP_MUTATIONS_PER_WEEK=1`. Proves
        the bypass is scoped to reviewer emails, not a global removal
        of the quota check."""
        monkeypatch.setenv("MAX_TRIPS_PER_USER", "10")
        monkeypatch.setenv("MAX_TRIP_MUTATIONS_PER_WEEK", "1")
        from app.config import reset_settings_cache

        reset_settings_cache()

        r1 = patched_app.post(
            "/api/v1/trips",
            json={
                "origin_address": "origin-1",
                "destination_address": "destination-1",
            },
        )
        assert r1.status_code == 201, r1.text

        r2 = patched_app.post(
            "/api/v1/trips",
            json={
                "origin_address": "origin-2",
                "destination_address": "destination-2",
            },
        )
        assert r2.status_code == 429, r2.text


def test_patch_trip_skips_validation_when_addresses_unchanged(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    stub = _install_validator(monkeypatch, invalid=set())
    r = patched_app.patch(
        "/api/v1/trips/slug-00001",
        json={
            "origin_address": "100 Main St",
            "destination_address": "200 Oak Ave",
        },
    )
    assert r.status_code == 200
    # Nothing actually changed, so the validator should be untouched.
    assert stub.calls == []


def test_patch_trip_swap_skips_validation(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    # Both addresses would be "invalid" per the stub, but a swap is
    # reusing already-stored values, so we skip validation.
    stub = _install_validator(
        monkeypatch, invalid={"100 Main St", "200 Oak Ave"}
    )
    r = patched_app.patch("/api/v1/trips/slug-00001", json={"swap_addresses": True})
    assert r.status_code == 200
    assert stub.calls == []


# ---------------------------------------------------------------------------
# Weekly mutation quota
# ---------------------------------------------------------------------------


def test_quota_endpoint_includes_mutation_counters(
    patched_app: TestClient,
) -> None:
    """The /quota endpoint should expose the rolling mutation budget."""
    from app.config import get_settings

    settings = get_settings()
    r = patched_app.get("/api/v1/trips/quota")
    assert r.status_code == 200
    body = r.json()
    assert body["used"] == 0
    assert body["limit"] == settings.max_trips_per_user
    assert body["mutations_used"] == 0
    assert body["mutations_limit"] == settings.max_trip_mutations_per_week
    assert body["mutations_oldest_age_seconds"] is None


def test_create_trip_logs_a_mutation(
    patched_app: TestClient, fake_mutation_log: list[dict]
) -> None:
    r = patched_app.post(
        "/api/v1/trips",
        json={"origin_address": "100 Main St", "destination_address": "200 Oak Ave"},
    )
    assert r.status_code == 201
    assert len(fake_mutation_log) == 1
    assert fake_mutation_log[0]["kind"] == "create"


def test_create_trip_429_when_at_mutation_cap(
    patched_app: TestClient,
    fake_mutation_log: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_TRIP_MUTATIONS_PER_WEEK", "2")
    from app.config import reset_settings_cache

    reset_settings_cache()

    # Pre-fill 2 mutations -> at the cap.
    for _ in range(2):
        fake_mutation_log.append({"user_id": 99, "trip_id": 1, "kind": "create"})

    r = patched_app.post(
        "/api/v1/trips",
        json={
            "origin_address": "100 Main St",
            "destination_address": "200 Oak Ave",
        },
    )
    assert r.status_code == 429
    assert "weekly trip changes" in r.json()["detail"].lower()
    assert "Retry-After" in r.headers


def test_patch_name_only_does_not_count(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_mutation_log: list[dict],
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    r = patched_app.patch("/api/v1/trips/slug-00001", json={"name": "Renamed"})
    assert r.status_code == 200
    # Name-only patch is free; mutation log untouched.
    assert fake_mutation_log == []


def test_patch_address_change_logs_a_mutation(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_mutation_log: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    _install_validator(monkeypatch, invalid=set())
    r = patched_app.patch(
        "/api/v1/trips/slug-00001", json={"origin_address": "999 Different St"}
    )
    assert r.status_code == 200
    assert len(fake_mutation_log) == 1
    assert fake_mutation_log[0]["kind"] == "address_change"


def test_patch_swap_logs_a_mutation(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_mutation_log: list[dict],
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    r = patched_app.patch("/api/v1/trips/slug-00001", json={"swap_addresses": True})
    assert r.status_code == 200
    assert len(fake_mutation_log) == 1
    assert fake_mutation_log[0]["kind"] == "swap"


def test_patch_address_change_429_when_at_cap(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_mutation_log: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_TRIP_MUTATIONS_PER_WEEK", "2")
    from app.config import reset_settings_cache

    reset_settings_cache()

    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="A",
        destination_address="B",
        created_at=None,
    )
    fake_mutation_log.extend(
        [
            {"user_id": 99, "trip_id": 1, "kind": "create"},
            {"user_id": 99, "trip_id": 1, "kind": "address_change"},
        ]
    )

    stub = _install_validator(monkeypatch, invalid=set())
    r = patched_app.patch(
        "/api/v1/trips/slug-00001", json={"origin_address": "C is different"}
    )
    assert r.status_code == 429
    # Crucially: we 429 *before* paying for Geocoding.
    assert stub.calls == []


def test_delete_trip_does_not_consume_mutation(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_mutation_log: list[dict],
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="A",
        destination_address="B",
        created_at=None,
    )
    r = patched_app.delete("/api/v1/trips/slug-00001")
    assert r.status_code == 204
    assert fake_mutation_log == []


# ---------------------------------------------------------------------------
# Dual-week backfill on create / address edit + ?week= query parameter
# ---------------------------------------------------------------------------


def test_create_trip_backfills_both_current_and_next_week(
    patched_app: TestClient,
    fake_backfill_kickoffs: list[tuple[int, str]],
) -> None:
    """A trip create should enqueue backfills for *both* weeks.

    This is what gives the user immediate access to the next-week
    toggle without waiting for the next Monday-01:00 cron.
    """
    from app.services.trips import current_week_start, next_week_start

    r = patched_app.post(
        "/api/v1/trips",
        json={
            "origin_address": "100 Main St",
            "destination_address": "200 Oak Ave",
        },
    )
    assert r.status_code == 201

    # The kickoff list captures (int trip_id, week) pairs; the create
    # in this test produces exactly one trip, so all entries belong to
    # it. Just assert the set of weeks is right.
    weeks = sorted(week for _tid, week in fake_backfill_kickoffs)
    assert weeks == sorted(
        [current_week_start().isoformat(), next_week_start().isoformat()]
    )


def test_patch_address_change_backfills_both_weeks(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_backfill_kickoffs: list[tuple[int, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    _install_validator(monkeypatch, invalid=set())

    r = patched_app.patch(
        "/api/v1/trips/slug-00001", json={"origin_address": "999 Different St"}
    )
    assert r.status_code == 200

    from app.services.trips import current_week_start, next_week_start

    weeks = sorted(week for tid, week in fake_backfill_kickoffs if tid == 1)
    assert weeks == sorted(
        [current_week_start().isoformat(), next_week_start().isoformat()]
    )


def test_patch_name_only_does_not_kickoff_any_backfill(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_backfill_kickoffs: list[tuple[int, str]],
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="A",
        destination_address="B",
        created_at=None,
    )
    r = patched_app.patch("/api/v1/trips/slug-00001", json={"name": "renamed"})
    assert r.status_code == 200
    assert fake_backfill_kickoffs == []


def test_patch_swap_backfills_both_weeks(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_backfill_kickoffs: list[tuple[int, str]],
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="100 Main St",
        destination_address="200 Oak Ave",
        created_at=None,
    )
    r = patched_app.patch("/api/v1/trips/slug-00001", json={"swap_addresses": True})
    assert r.status_code == 200

    from app.services.trips import current_week_start, next_week_start

    weeks = sorted(week for tid, week in fake_backfill_kickoffs if tid == 1)
    assert weeks == sorted(
        [current_week_start().isoformat(), next_week_start().isoformat()]
    )


def test_heatmap_default_returns_current_week_with_flag(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )
    r = patched_app.get("/api/v1/trips/slug-00001/heatmap")
    assert r.status_code == 200

    from app.services.trips import current_week_start

    body = r.json()
    assert body["week_start_date"] == current_week_start().isoformat()
    assert body["next_week_available"] is False


def test_heatmap_week_next_returns_next_week_data(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )
    r = patched_app.get("/api/v1/trips/slug-00001/heatmap?week=next")
    assert r.status_code == 200

    from app.services.trips import next_week_start

    body = r.json()
    assert body["week_start_date"] == next_week_start().isoformat()


def test_heatmap_next_week_available_flag_flips_when_populated(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_next_week_available: dict[str, bool],
) -> None:
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )
    fake_next_week_available["value"] = True
    r = patched_app.get("/api/v1/trips/slug-00001/heatmap")
    assert r.status_code == 200
    assert r.json()["next_week_available"] is True


def test_heatmap_rejects_invalid_week_param(
    patched_app: TestClient, fake_trips_store: dict[int, Trip]
) -> None:
    """Anything outside {current, next} should be a 422 from FastAPI."""
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )
    r = patched_app.get("/api/v1/trips/slug-00001/heatmap?week=last")
    assert r.status_code == 422


def test_backfill_status_week_next_does_not_kickoff(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_backfill_kickoffs: list[tuple[int, str]],
) -> None:
    """`?week=next` is read-only — only the cron + create/edit may write next week."""
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )
    r = patched_app.get("/api/v1/trips/slug-00001/backfill-status?week=next")
    assert r.status_code == 200
    assert fake_backfill_kickoffs == []


def test_backfill_status_week_current_still_self_heals(
    patched_app: TestClient,
    fake_trips_store: dict[int, Trip],
    fake_backfill_kickoffs: list[tuple[int, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current-week self-heal path keeps working: 0 samples → enqueue."""
    fake_trips_store[1] = _make_trip(
        id=1,
        user_id=99,
        name="x",
        origin_address="a",
        destination_address="b",
        created_at=None,
    )

    import app.api.trips_api as trips_api_mod

    monkeypatch.setattr(
        trips_api_mod,
        "sample_status_for_trip",
        lambda _tid, _ws: {"total": 0, "ready": 0},
    )

    r = patched_app.get("/api/v1/trips/slug-00001/backfill-status?week=current")
    assert r.status_code == 200

    from app.services.trips import current_week_start

    assert fake_backfill_kickoffs == [(1, current_week_start().isoformat())]
