"""Unit tests for the pure helpers in `app.job.data_gathering`."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.job import data_gathering as dg
from app.services.trips import Trip

TZ = ZoneInfo("America/Los_Angeles")


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "app_env": "local",
        "commute_window_start_hour": 6,
        "commute_window_end_hour": 21,
        "commute_interval_minutes": 15,
        "commute_days_per_week": 7,
        "commute_throttle_every": 0,
        "max_weekly_routes_calls": 10_000,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_next_week_monday_skips_to_next_week() -> None:
    # Tuesday 2025-11-11 → next Monday is 2025-11-17.
    assert dg.next_week_monday(date(2025, 11, 11)) == date(2025, 11, 17)


def test_next_week_monday_from_sunday() -> None:
    # Sunday 2025-11-16 → next Monday is still 2025-11-17.
    assert dg.next_week_monday(date(2025, 11, 16)) == date(2025, 11, 17)


def test_current_week_monday_from_wednesday() -> None:
    assert dg.current_week_monday(date(2025, 11, 12)) == date(2025, 11, 10)


def test_slots_per_trip_per_week_default_window() -> None:
    settings = _settings()
    # (21-6) * 60 / 15 = 60 slots/day; 60 * 7 * 2 directions = 840.
    assert dg.slots_per_trip_per_week(settings) == 840


def test_slots_for_day_is_start_inclusive_end_exclusive() -> None:
    settings = _settings()
    day = date(2025, 11, 10)  # Monday
    slots = dg._slots_for_day(day, settings)

    assert slots[0] == datetime(2025, 11, 10, 6, 0, tzinfo=TZ)
    assert slots[-1] == datetime(2025, 11, 10, 20, 45, tzinfo=TZ)
    assert len(slots) == 60


class TestQueryDepartureTime:
    """`_query_departure_time` keeps future slots and shifts past ones forward.

    The shift is by full week multiples so the returned timestamp is the
    same weekday + same hh:mm as the slot, which is what gives a
    week-cyclical traffic prediction.
    """

    def test_future_slot_is_returned_unchanged(self) -> None:
        now = datetime(2026, 4, 30, 9, 49, tzinfo=TZ)  # Thu
        slot = datetime(2026, 5, 2, 14, 0, tzinfo=TZ)  # Sat next week
        assert dg._query_departure_time(slot, now=now) == slot

    def test_past_slot_in_current_week_shifts_one_week(self) -> None:
        now = datetime(2026, 4, 30, 9, 49, tzinfo=TZ)  # Thu
        slot = datetime(2026, 4, 27, 8, 0, tzinfo=TZ)  # Mon this week
        result = dg._query_departure_time(slot, now=now)
        assert result == datetime(2026, 5, 4, 8, 0, tzinfo=TZ)
        assert result.weekday() == slot.weekday()
        assert (result.hour, result.minute) == (slot.hour, slot.minute)

    def test_multi_week_stale_slot_shifts_multiple_weeks(self) -> None:
        # Apr 16 8am (Thu) is two weeks back. Apr 30 8am (today) is
        # also still in the past relative to `now=09:49`, so the
        # smallest forward shift that clears the buffer is +21 days.
        now = datetime(2026, 4, 30, 9, 49, tzinfo=TZ)
        slot = datetime(2026, 4, 16, 8, 0, tzinfo=TZ)
        result = dg._query_departure_time(slot, now=now)
        assert result == datetime(2026, 5, 7, 8, 0, tzinfo=TZ)
        assert result.weekday() == slot.weekday()
        assert (result.hour, result.minute) == (slot.hour, slot.minute)

    def test_slot_equal_to_now_is_shifted_past_buffer(self) -> None:
        # `slot_ts == now` would otherwise sail through and Google would
        # see a past timestamp once the request lands. The 2-minute
        # buffer forces a forward shift.
        now = datetime(2026, 4, 30, 9, 49, tzinfo=TZ)
        slot = now
        result = dg._query_departure_time(slot, now=now)
        assert result == now + timedelta(days=7)

    def test_slot_just_inside_buffer_still_shifts(self) -> None:
        # 1 minute in the future is *inside* the 2-minute safety buffer.
        now = datetime(2026, 4, 30, 9, 49, tzinfo=TZ)
        slot = now + timedelta(minutes=1)
        result = dg._query_departure_time(slot, now=now)
        assert result > now + timedelta(minutes=2)

    def test_slot_just_outside_buffer_is_unchanged(self) -> None:
        now = datetime(2026, 4, 30, 9, 49, tzinfo=TZ)
        slot = now + timedelta(minutes=3)
        assert dg._query_departure_time(slot, now=now) == slot

    def test_default_now_is_used_when_omitted(self) -> None:
        # Stale slot with no explicit `now`: must come back strictly
        # in the future of wall-clock time.
        slot = datetime(2020, 1, 1, 8, 0, tzinfo=TZ)
        result = dg._query_departure_time(slot)
        assert result > datetime.now(TZ)
        # Same weekday + hh:mm preserved across the multi-year shift.
        assert result.weekday() == slot.weekday()
        assert (result.hour, result.minute) == (slot.hour, slot.minute)


def test_duration_string_parsing() -> None:
    assert dg._duration_string_to_seconds("1234s") == 1234
    assert dg._duration_string_to_seconds("0s") == 0
    assert dg._duration_string_to_seconds(None) is None
    assert dg._duration_string_to_seconds("") is None
    assert dg._duration_string_to_seconds("garbage") is None


def test_origin_destination_flips_for_return() -> None:
    trip = Trip(
        id=1,
        slug="slug-00001",
        user_id=1,
        name=None,
        origin_address="A",
        destination_address="B",
        created_at=None,
    )
    assert dg._origin_destination(trip, "outbound") == ("A", "B")
    assert dg._origin_destination(trip, "return") == ("B", "A")


def test_plan_and_run_no_trips_is_a_noop(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _settings()
    provider_calls: list[tuple] = []

    class FakeProvider:
        def fetch(self, *args, **kwargs):  # noqa: ARG002
            provider_calls.append(args)

    with caplog.at_level("INFO"):
        dg._plan_and_run(
            trips=[],
            week_start=date(2025, 11, 10),
            provider=FakeProvider(),
            settings=settings,
            enforce_ceiling=True,
        )

    assert provider_calls == []
    assert any("nothing to do" in rec.message for rec in caplog.records)


def test_plan_and_run_enforces_ceiling(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Budget above the ceiling should abort before any DB/provider call."""
    settings = _settings(max_weekly_routes_calls=500)
    trip = Trip(
        id=1,
        slug="slug-00001",
        user_id=1,
        name="T",
        origin_address="A",
        destination_address="B",
        created_at=None,
    )

    calls: list[str] = []

    def fake_upsert(**_kw):
        calls.append("upsert")
        return 0

    def fake_fill(**_kw):
        calls.append("fill")
        return {"updated": 0, "errors": 0}

    monkeypatch.setattr(dg, "_upsert_empty_slots", fake_upsert)
    monkeypatch.setattr(dg, "_fill_in_slots_for_trip", fake_fill)

    class DummyProvider:
        def fetch(self, *args, **kwargs):  # noqa: ARG002
            raise AssertionError("should not be called")

    with caplog.at_level("ERROR"):
        dg._plan_and_run(
            trips=[trip],
            week_start=date(2025, 11, 10),
            provider=DummyProvider(),
            settings=settings,
            enforce_ceiling=True,
        )

    assert calls == []  # neither upsert nor fill invoked
    assert any(
        "exceeds MAX_WEEKLY_ROUTES_CALLS" in rec.message for rec in caplog.records
    )


class TestFillInSlotsAbortsOnSoftDelete:
    """Mid-loop `_trip_is_soft_deleted` flip stops further provider calls.

    The check piggy-backs on the throttle boundary, so with
    `commute_throttle_every=N` the loop runs N slots and *then* notices
    the soft-delete on the post-batch check, exiting the loop. We
    deliberately don't check more often than that to avoid an extra DB
    round-trip per slot.
    """

    @staticmethod
    def _trip() -> Trip:
        return Trip(
            id=42,
            slug="slug-00042",
            user_id=1,
            name="T",
            origin_address="A",
            destination_address="B",
            created_at=None,
        )

    @staticmethod
    def _pending(n: int) -> list[dict]:
        # Use future timestamps so `_query_departure_time` is a no-op
        # and we don't depend on wall-clock for the test.
        base = datetime.now(TZ) + timedelta(days=14)
        return [
            {
                "id": i + 1,
                "trip_id": 42,
                "direction": "outbound",
                "departure_time_rfc3339": (
                    base + timedelta(minutes=15 * i)
                ).isoformat(),
            }
            for i in range(n)
        ]

    @staticmethod
    def _fake_db_factory():
        class _Cursor:
            def __init__(self) -> None:
                self.executes: list = []
                self.rowcount = 1

            def execute(self, query, values=None) -> None:
                self.executes.append((query, values))

        cursor = _Cursor()

        class _DB:
            def __enter__(self_inner):
                return cursor

            def __exit__(self_inner, *exc) -> None:
                return None

        return _DB, cursor

    def test_loop_breaks_at_throttle_boundary_when_soft_deleted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(commute_throttle_every=3, commute_throttle_seconds=0)

        # 10 pending slots: with throttle_every=3, the loop processes
        # slots 1-3, hits the boundary, sees the soft-delete, breaks.
        pending = self._pending(10)
        monkeypatch.setattr(dg, "_fetch_pending_slots", lambda *_a, **_kw: pending)

        db_cls, _cursor = self._fake_db_factory()
        monkeypatch.setattr(dg, "Database", db_cls)

        # Soft-delete is True from the very first check.
        delete_check_calls: list[int] = []

        def fake_check(trip_id: int) -> bool:
            delete_check_calls.append(trip_id)
            return True

        monkeypatch.setattr(dg, "_trip_is_soft_deleted", fake_check)

        # Sleep should never be reached: the abort runs before sleep.
        monkeypatch.setattr(
            dg.time,
            "sleep",
            lambda *_a, **_kw: pytest.fail("sleep called after abort"),
        )

        provider_calls: list[tuple] = []

        class FakeProvider:
            def fetch(self, *args, **kwargs):  # noqa: ARG002
                provider_calls.append(args)
                return type(
                    "R",
                    (),
                    {
                        "distance_meters": 100,
                        "duration": "60s",
                        "condition": "OK",
                        "status_code": "OK",
                        "status_message": None,
                    },
                )()

        result = dg._fill_in_slots_for_trip(
            trip=self._trip(),
            week_start=date(2025, 11, 10),
            provider=FakeProvider(),
            settings=settings,
        )

        # Exactly one throttle-batch worth of provider calls — no more.
        assert len(provider_calls) == 3
        # The soft-delete check fires at the boundary.
        assert delete_check_calls == [42]
        assert result == {"updated": 3, "errors": 0}

    def test_loop_continues_when_not_soft_deleted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative control: an active trip runs to completion."""
        settings = _settings(commute_throttle_every=3, commute_throttle_seconds=0)
        pending = self._pending(5)
        monkeypatch.setattr(dg, "_fetch_pending_slots", lambda *_a, **_kw: pending)

        db_cls, _cursor = self._fake_db_factory()
        monkeypatch.setattr(dg, "Database", db_cls)

        check_count = 0

        def fake_check(trip_id: int) -> bool:
            nonlocal check_count
            check_count += 1
            return False

        monkeypatch.setattr(dg, "_trip_is_soft_deleted", fake_check)
        monkeypatch.setattr(dg.time, "sleep", lambda *_a, **_kw: None)

        provider_calls: list[int] = []

        class FakeProvider:
            def fetch(self, *_args, **_kwargs):
                provider_calls.append(1)
                return type(
                    "R",
                    (),
                    {
                        "distance_meters": 100,
                        "duration": "60s",
                        "condition": "OK",
                        "status_code": "OK",
                        "status_message": None,
                    },
                )()

        result = dg._fill_in_slots_for_trip(
            trip=self._trip(),
            week_start=date(2025, 11, 10),
            provider=FakeProvider(),
            settings=settings,
        )

        assert len(provider_calls) == 5  # all slots processed
        assert check_count == 1  # one boundary at idx=2 (slots 1-3)
        assert result == {"updated": 5, "errors": 0}


def test_plan_and_run_bypasses_ceiling_for_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`enforce_ceiling=False` should still run when the nominal budget is high."""
    settings = _settings(max_weekly_routes_calls=1)
    trip = Trip(
        id=7,
        slug="slug-00007",
        user_id=1,
        name="T",
        origin_address="A",
        destination_address="B",
        created_at=None,
    )

    upserts: list[int] = []
    fills: list[int] = []

    def fake_upsert(**kw):
        upserts.append(kw["trip_id"])
        return 0

    def fake_fill(**kw):
        fills.append(kw["trip"].id)
        return {"updated": 0, "errors": 0}

    monkeypatch.setattr(dg, "_upsert_empty_slots", fake_upsert)
    monkeypatch.setattr(dg, "_fill_in_slots_for_trip", fake_fill)

    class DummyProvider:
        def fetch(self, *args, **kwargs):  # noqa: ARG002
            return None

    dg._plan_and_run(
        trips=[trip],
        week_start=date(2025, 11, 10),
        provider=DummyProvider(),
        settings=settings,
        enforce_ceiling=False,
    )

    assert upserts == [7]
    assert fills == [7]


class _NoopProvider:
    """Implements `CommuteProvider` for tests that never actually fetch."""

    def fetch(self, *_args, **_kwargs):
        from app.job.providers import CommuteResult

        return CommuteResult(
            distance_meters=0,
            duration="0s",
            condition=None,
            status_code="OK",
            status_message=None,
        )


class TestBackfillTripForWeek:
    """`backfill_trip_for_week` dispatches `_plan_and_run` for the given week.

    Used both by the API layer (which fires it for the current AND next
    week on each billed mutation) and by the legacy
    `backfill_trip_current_week` wrapper.
    """

    @staticmethod
    def _stub_db_with_trip(monkeypatch: pytest.MonkeyPatch) -> None:
        class _Cursor:
            def __init__(self) -> None:
                self.rowcount = 1
                # Matches the SELECT order in data_gathering.backfill_trip_for_week:
                # id, slug, user_id, name, origin_address, destination_address, created_at
                self._row = (7, "slug-00007", 1, "T", "A", "B", None)

            def execute(self, *_args, **_kw) -> None:
                pass

            def fetchone(self):
                return self._row

        class _DB:
            def __enter__(self_inner):
                return _Cursor()

            def __exit__(self_inner, *exc) -> None:
                return None

        monkeypatch.setattr(dg, "Database", _DB)

    def test_targets_the_caller_specified_week(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_db_with_trip(monkeypatch)

        plan_calls: list[date] = []

        def fake_plan(*, trips, week_start, **_kw):  # noqa: ARG001
            plan_calls.append(week_start)

        monkeypatch.setattr(dg, "_plan_and_run", fake_plan)

        target = date(2025, 12, 8)
        dg.backfill_trip_for_week(
            7, target, provider=_NoopProvider(), settings=_settings()
        )

        assert plan_calls == [target]

    def test_unknown_trip_is_a_logged_noop(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _Cursor:
            rowcount = 0

            def execute(self, *_args, **_kw) -> None:
                pass

            def fetchone(self):
                return None

        class _DB:
            def __enter__(self_inner):
                return _Cursor()

            def __exit__(self_inner, *exc) -> None:
                return None

        monkeypatch.setattr(dg, "Database", _DB)

        called: list[date] = []

        def fake_plan(*, week_start, **_kw):  # noqa: ARG001
            called.append(week_start)

        monkeypatch.setattr(dg, "_plan_and_run", fake_plan)

        with caplog.at_level("WARNING"):
            dg.backfill_trip_for_week(
                999,
                date(2025, 12, 8),
                provider=_NoopProvider(),
                settings=_settings(),
            )

        assert called == []
        assert any("not found" in rec.message for rec in caplog.records)

    def test_legacy_wrapper_still_targets_current_week(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`backfill_trip_current_week` is the API-compatible older entrypoint."""
        self._stub_db_with_trip(monkeypatch)

        plan_calls: list[date] = []

        def fake_plan(*, week_start, **_kw):  # noqa: ARG001
            plan_calls.append(week_start)

        monkeypatch.setattr(dg, "_plan_and_run", fake_plan)

        dg.backfill_trip_current_week(
            7, provider=_NoopProvider(), settings=_settings()
        )

        assert plan_calls == [dg.current_week_monday()]


class TestReviewAccountShortCircuit:
    """The two cost-control paths that fire for App Store / Play Store
    reviewer accounts:

      1. The weekly Monday 01:00 PT cron filters out reviewer-owned
         trips before they ever reach `_plan_and_run`, so the cron
         doesn't burn ~840 Routes Matrix calls/week per reviewer trip.
      2. On-create / on-edit backfill (`backfill_trip_for_week`) routes
         reviewer-owned trips to `FixtureProvider` when the caller
         didn't pin a provider — even if `data_provider=google` is set
         globally. The explicit `provider=` kwarg still wins so tests
         that inject deterministic fakes keep working.
    """

    @staticmethod
    def _trip(trip_id: int, user_id: int) -> Trip:
        return Trip(
            id=trip_id,
            slug=f"slug-{trip_id:05d}",
            user_id=user_id,
            name=f"T{trip_id}",
            origin_address="A",
            destination_address="B",
            created_at=None,
        )

    @staticmethod
    def _stub_users(monkeypatch: pytest.MonkeyPatch, email_by_id: dict[int, str]) -> None:
        """Patch `get_user_by_id` to look up emails from the given map.

        Returns `None` for unknown ids so the helper exercises its
        "owner row is gone" fallback too.
        """
        from app.services.users import User

        def fake(user_id: int) -> User | None:
            email = email_by_id.get(user_id)
            if email is None:
                return None
            return User(
                id=user_id,
                google_sub=None,
                apple_sub=None,
                email=email,
                name=None,
                picture_url=None,
            )

        monkeypatch.setattr(dg, "get_user_by_id", fake)

    def test_filter_drops_reviewer_trips(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            review_account_emails=["my.app.store.reviewer@gmail.com"]
        )
        self._stub_users(
            monkeypatch,
            {
                1: "real.user@example.com",
                2: "my.app.store.reviewer@gmail.com",
                3: "another.real@example.com",
            },
        )

        trips = [self._trip(101, 1), self._trip(102, 2), self._trip(103, 3)]
        kept = dg._filter_out_review_account_trips(trips, settings)

        assert [t.id for t in kept] == [101, 103]

    def test_filter_is_a_noop_when_no_reviewers_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty list → no DB lookups, original list returned. This
        keeps the cron path fast in environments that haven't
        configured a reviewer (i.e. local / dev / forks)."""
        settings = _settings(review_account_emails=[])

        def fake_lookup(_user_id: int):
            raise AssertionError("get_user_by_id should not be called")

        monkeypatch.setattr(dg, "get_user_by_id", fake_lookup)

        trips = [self._trip(101, 1), self._trip(102, 2)]
        kept = dg._filter_out_review_account_trips(trips, settings)

        assert kept == trips

    def test_filter_keeps_trips_with_missing_owner_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If `get_user_by_id` returns None (race: user row deleted
        mid-cron), the trip stays in the list so the existing
        FK-cascade / orphan-trip logic in `_plan_and_run` handles it
        uniformly — we don't silently drop trips on a missing owner."""
        settings = _settings(
            review_account_emails=["my.app.store.reviewer@gmail.com"]
        )
        self._stub_users(monkeypatch, {})  # every lookup returns None

        trips = [self._trip(101, 1), self._trip(102, 2)]
        kept = dg._filter_out_review_account_trips(trips, settings)

        assert kept == trips

    def test_main_skips_reviewer_trips_end_to_end(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`main()` (the weekly cron) must hand `_plan_and_run` a trip
        list with reviewer-owned trips filtered out."""
        settings = _settings(
            review_account_emails=["my.app.store.reviewer@gmail.com"]
        )
        trips = [self._trip(101, 1), self._trip(102, 2)]
        monkeypatch.setattr(dg, "list_active_trips", lambda: trips)
        self._stub_users(
            monkeypatch,
            {
                1: "real.user@example.com",
                2: "my.app.store.reviewer@gmail.com",
            },
        )

        plan_call_trips: list[list[Trip]] = []

        def fake_plan(*, trips, **_kw):  # noqa: ARG001
            plan_call_trips.append(list(trips))

        monkeypatch.setattr(dg, "_plan_and_run", fake_plan)

        dg.main(provider=_NoopProvider(), settings=settings)

        assert len(plan_call_trips) == 1
        assert [t.id for t in plan_call_trips[0]] == [101]

    def test_backfill_routes_reviewer_to_fixture_provider_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the caller doesn't pin a provider AND `data_provider=google`,
        a reviewer-owned trip still gets `FixtureProvider`."""
        from app.job.providers import FixtureProvider, GoogleRoutesProvider

        # data_provider=google with a key would normally pick
        # GoogleRoutesProvider for everyone.
        settings = _settings(
            data_provider="google",
            google_maps_api_key="abc",
            review_account_emails=["my.app.store.reviewer@gmail.com"],
        )

        class _Cursor:
            rowcount = 1
            # SELECT order: id, slug, user_id, name, origin, dest, created_at
            _row = (7, "slug-00007", 42, "T", "A", "B", None)

            def execute(self, *_a, **_kw) -> None:
                pass

            def fetchone(self):
                return self._row

        class _DB:
            def __enter__(self_inner):
                return _Cursor()

            def __exit__(self_inner, *exc) -> None:
                return None

        monkeypatch.setattr(dg, "Database", _DB)
        self._stub_users(monkeypatch, {42: "my.app.store.reviewer@gmail.com"})

        plan_providers: list[object] = []

        def fake_plan(*, provider, **_kw):  # noqa: ARG001
            plan_providers.append(provider)

        monkeypatch.setattr(dg, "_plan_and_run", fake_plan)

        dg.backfill_trip_for_week(7, date(2025, 12, 8), settings=settings)

        assert len(plan_providers) == 1
        assert isinstance(plan_providers[0], FixtureProvider)
        assert not isinstance(plan_providers[0], GoogleRoutesProvider)

    def test_backfill_routes_real_user_to_google_provider_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative control: a normal user with `data_provider=google`
        still gets the real Google provider — reviewer logic must not
        accidentally route everyone to FixtureProvider."""
        from app.job.providers import GoogleRoutesProvider

        settings = _settings(
            data_provider="google",
            google_maps_api_key="abc",
            review_account_emails=["my.app.store.reviewer@gmail.com"],
        )

        class _Cursor:
            rowcount = 1
            _row = (8, "slug-00008", 99, "T", "A", "B", None)

            def execute(self, *_a, **_kw) -> None:
                pass

            def fetchone(self):
                return self._row

        class _DB:
            def __enter__(self_inner):
                return _Cursor()

            def __exit__(self_inner, *exc) -> None:
                return None

        monkeypatch.setattr(dg, "Database", _DB)
        self._stub_users(monkeypatch, {99: "real.user@example.com"})

        plan_providers: list[object] = []

        def fake_plan(*, provider, **_kw):  # noqa: ARG001
            plan_providers.append(provider)

        monkeypatch.setattr(dg, "_plan_and_run", fake_plan)

        dg.backfill_trip_for_week(8, date(2025, 12, 8), settings=settings)

        assert len(plan_providers) == 1
        assert isinstance(plan_providers[0], GoogleRoutesProvider)

    def test_explicit_provider_kwarg_still_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests / admin tooling that pass `provider=...` directly must
        keep getting that provider — the reviewer fallback is only for
        the default `provider=None` path."""
        settings = _settings(
            review_account_emails=["my.app.store.reviewer@gmail.com"]
        )

        class _Cursor:
            rowcount = 1
            _row = (9, "slug-00009", 1, "T", "A", "B", None)

            def execute(self, *_a, **_kw) -> None:
                pass

            def fetchone(self):
                return self._row

        class _DB:
            def __enter__(self_inner):
                return _Cursor()

            def __exit__(self_inner, *exc) -> None:
                return None

        monkeypatch.setattr(dg, "Database", _DB)

        # Note: no user lookup is stubbed — when the caller pins
        # provider= we must NOT do a user lookup (that's the contract).
        def fake_lookup(_user_id: int):
            raise AssertionError("get_user_by_id called despite explicit provider")

        monkeypatch.setattr(dg, "get_user_by_id", fake_lookup)

        explicit = _NoopProvider()
        plan_providers: list[object] = []

        def fake_plan(*, provider, **_kw):  # noqa: ARG001
            plan_providers.append(provider)

        monkeypatch.setattr(dg, "_plan_and_run", fake_plan)

        dg.backfill_trip_for_week(
            9, date(2025, 12, 8), provider=explicit, settings=settings
        )

        assert plan_providers == [explicit]
