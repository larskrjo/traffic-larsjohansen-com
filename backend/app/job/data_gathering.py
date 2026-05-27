"""Weekly multi-trip commute-data gathering.

What runs on the Monday 01:00 PT cron (`main()`):

    1. Enumerate every active trip.
    2. For each trip, in both directions, for each day Mon-Sun, generate
       slots at 15-minute intervals from 06:00-21:00 local time.
    3. Fail-closed abort if the total call count for the week would exceed
       `Settings.max_weekly_routes_calls`. Better to skip than accidentally
       burn through the Google Routes Matrix budget.
    4. Upsert empty samples first so the frontend immediately sees a
       "0 / N ready" status for the upcoming week.
    5. Fill them in by calling the configured `CommuteProvider`.

    The cron targets `next_week_monday()` so users always see the
    upcoming week pre-populated alongside the current one for the
    rest of the week.

What runs when a user creates or address-edits a trip (`backfill_trip_for_week`):

    Same as above but for exactly one trip and a caller-specified week.
    The API layer fires this for *both* the current and next week on
    every billed mutation so the new/edited trip immediately matches
    the "two weeks always visible" invariant the cron maintains for
    fleet-wide trips.

Mid-backfill cancellation:

    A user can delete a trip while its initial backfill is still
    looping through ~840 slots. Since each slot costs a Routes Matrix
    call (real money), we re-check `trips.deleted_at` once per throttle
    batch and break the loop if it flips. Worst-case waste is one
    throttle-batch of calls; typical waste is well under a dollar.

Past-slot handling:

    Routes Matrix rejects `departureTime` values in the past, so when
    we backfill the current week mid-week, the already-elapsed slots
    (e.g. Monday morning when a trip is created Thursday) would all
    fail with INVALID_ARGUMENT and stay grey on the heatmap. To avoid
    that, when we *call* the provider for a row whose stored
    `departure_time_rfc3339` is in the past, we shift the timestamp
    forward by N*7 days into the future before sending it. Same
    weekday + same hh:mm gives the same week-cyclical traffic
    prediction, which is the right value for the heatmap cell.

    The DB still stores the original slot timestamp (so the unique
    key `(trip_id, direction, departure_time_rfc3339)` keeps its
    natural meaning and the weekly cron's next-week run doesn't
    collide with a backfill that already touched those future
    timestamps).
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Literal

from mysql.connector import Error

from app.config import Settings, get_settings
from app.db.db import Database, get_pool
from app.job.providers import CommuteProvider, get_provider, provider_for_user_email
from app.services.trips import TZ, Trip, list_active_trips
from app.services.users import get_user_by_id

logger = logging.getLogger(__name__)

Direction = Literal["outbound", "return"]
DIRECTIONS: tuple[Direction, Direction] = ("outbound", "return")


def _monday_of_week(target: date) -> date:
    return target - timedelta(days=target.weekday())


def next_week_monday(today: date | None = None) -> date:
    today = today or datetime.now(TZ).date()
    return _monday_of_week(today) + timedelta(days=7)


def current_week_monday(today: date | None = None) -> date:
    today = today or datetime.now(TZ).date()
    return _monday_of_week(today)


# Buffer to cover request-side latency: a slot that's "now + 30 seconds"
# can still land at Google as a past departureTime once the request
# has hopped through our network and theirs. Two minutes is generous
# without being wasteful.
_FUTURE_BUFFER = timedelta(minutes=2)


def _query_departure_time(
    slot_ts: datetime, now: datetime | None = None
) -> datetime:
    """Shift a past slot timestamp forward by week multiples until it's safe to send.

    Routes Matrix requires `departureTime` to be in the future. For
    a past slot (typical when a user creates a trip mid-week and we
    backfill from this week's Monday), we add the smallest N*7 days
    that lands the timestamp comfortably past `now`. Because traffic
    patterns are weekly-cyclical, querying e.g. next Monday at 8am
    is the right prediction for "this Monday at 8am" on the heatmap.
    """
    now = now or datetime.now(slot_ts.tzinfo)
    cutoff = now + _FUTURE_BUFFER
    shifted = slot_ts
    while shifted <= cutoff:
        shifted += timedelta(days=7)
    return shifted


def _slots_for_day(day: date, settings: Settings) -> list[datetime]:
    start = datetime.combine(
        day, datetime.min.time().replace(hour=settings.commute_window_start_hour), TZ
    )
    end = datetime.combine(
        day, datetime.min.time().replace(hour=settings.commute_window_end_hour), TZ
    )
    out: list[datetime] = []
    cursor = start
    step = timedelta(minutes=settings.commute_interval_minutes)
    while cursor < end:
        out.append(cursor)
        cursor += step
    return out


def slots_per_trip_per_week(settings: Settings) -> int:
    """How many API calls one trip needs for a full week (both directions)."""
    slots_per_day = (
        (settings.commute_window_end_hour - settings.commute_window_start_hour)
        * 60
        // settings.commute_interval_minutes
    )
    return slots_per_day * settings.commute_days_per_week * len(DIRECTIONS)


def _origin_destination(trip: Trip, direction: Direction) -> tuple[str, str]:
    if direction == "outbound":
        return trip.origin_address, trip.destination_address
    return trip.destination_address, trip.origin_address


def _upsert_empty_slots(
    *, trip_id: int, week_start: date, settings: Settings
) -> int:
    """Create blank samples for every (day × time × direction) in `week_start`.

    Idempotent via the `uniq_sample_slot` unique key.
    Returns the number of rows freshly inserted (vs bumped).
    """
    days = [week_start + timedelta(days=i) for i in range(settings.commute_days_per_week)]
    inserted = 0

    insert_query = """
    INSERT INTO commute_samples
        (trip_id, week_start_date, direction, date_local, weekday, hhmm,
         local_departure_time, departure_time_rfc3339)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP
    """

    with Database() as cursor:
        for day in days:
            for ts in _slots_for_day(day, settings):
                for direction in DIRECTIONS:
                    values = (
                        trip_id,
                        week_start.isoformat(),
                        direction,
                        ts.date().isoformat(),
                        ts.weekday(),
                        ts.strftime("%H:%M"),
                        ts.strftime("%Y-%m-%d %H:%M:%S %Z"),
                        ts.isoformat(),
                    )
                    try:
                        cursor.execute(insert_query, values)
                        if int(cursor.rowcount or 0) == 1:
                            inserted += 1
                    except Error as exc:
                        logger.warning(
                            "Slot insert failed trip=%s dir=%s ts=%s: %s",
                            trip_id,
                            direction,
                            ts.isoformat(),
                            exc,
                        )
    return inserted


def _fetch_pending_slots(trip_id: int, week_start: date) -> list[dict]:
    """Rows that still need a duration filled in, ordered for cache locality."""
    pool = get_pool()
    connection = pool.get_connection()
    try:
        cur = connection.cursor(dictionary=True)
        cur.execute(
            """
            SELECT id, trip_id, direction, departure_time_rfc3339
            FROM commute_samples
            WHERE trip_id = %s AND week_start_date = %s
              AND (status_code IS NULL OR status_code = '' OR duration_seconds IS NULL)
            ORDER BY direction, departure_time_rfc3339
            """,
            (trip_id, week_start.isoformat()),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        connection.close()
    return list(rows)


def _trip_is_soft_deleted(trip_id: int) -> bool:
    """Return True iff `trips.deleted_at` is non-null for this trip.

    Used as an abort signal mid-backfill: if the user deletes a trip
    while we're walking its pending slots, we'd otherwise keep burning
    Routes Matrix calls (and dollars) for samples nothing reads. The
    check is a primary-key lookup, so it's cheap to run once per
    throttle batch.

    A trip that's been hard-deleted entirely is *also* treated as
    "soft-deleted" here — the row is gone, so the loop should stop
    just as much as if `deleted_at` had been stamped.
    """
    pool = get_pool()
    connection = pool.get_connection()
    try:
        cur = connection.cursor()
        cur.execute(
            "SELECT deleted_at FROM trips WHERE id = %s", (trip_id,)
        )
        row = cur.fetchone()
        cur.close()
    finally:
        connection.close()
    if row is None:
        return True
    return row[0] is not None


def _duration_string_to_seconds(value: str | None) -> int | None:
    """Parse Google's `"1234s"` duration string into integer seconds."""
    if not value:
        return None
    if isinstance(value, str) and value.endswith("s"):
        try:
            return int(value[:-1])
        except ValueError:
            return None
    return None


def _fill_in_slots_for_trip(
    *,
    trip: Trip,
    week_start: date,
    provider: CommuteProvider,
    settings: Settings,
) -> dict[str, int]:
    """Call the provider for every pending slot of this trip + week."""
    pending = _fetch_pending_slots(trip.id, week_start)
    if not pending:
        return {"updated": 0, "errors": 0}

    update_query = """
    UPDATE commute_samples
    SET distance_meters = %s,
        duration_seconds = %s,
        `condition` = %s,
        status_code = %s,
        status_message = %s,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = %s
    """

    updated = 0
    errors = 0

    with Database() as cursor:
        for idx, row in enumerate(pending):
            direction: Direction = row["direction"]
            origin, destination = _origin_destination(trip, direction)
            slot_ts = datetime.fromisoformat(row["departure_time_rfc3339"])
            query_ts = _query_departure_time(slot_ts)
            try:
                result = provider.fetch(
                    origin, destination, query_ts.isoformat(), direction
                )
            except Exception:
                logger.exception(
                    "Provider raised for trip=%s slot=%s", trip.id, row["id"]
                )
                errors += 1
                continue

            seconds = _duration_string_to_seconds(result.duration)

            values = (
                result.distance_meters,
                seconds,
                result.condition,
                result.status_code,
                result.status_message,
                row["id"],
            )
            try:
                cursor.execute(update_query, values)
                updated += 1
            except Error as exc:
                logger.warning("Update failed slot=%s: %s", row["id"], exc)
                errors += 1

            if (
                settings.commute_throttle_every
                and (idx + 1) % settings.commute_throttle_every == 0
            ):
                # Bail out if the user deleted the trip mid-backfill.
                # Bounded waste: at most one throttle-batch of Routes
                # Matrix calls before we notice and stop.
                if _trip_is_soft_deleted(trip.id):
                    logger.info(
                        "Trip %s soft-deleted mid-backfill; "
                        "aborting at slot %s/%s",
                        trip.id,
                        idx + 1,
                        len(pending),
                    )
                    break
                time.sleep(settings.commute_throttle_seconds)

    return {"updated": updated, "errors": errors}


def _plan_and_run(
    *,
    trips: list[Trip],
    week_start: date,
    provider: CommuteProvider,
    settings: Settings,
    enforce_ceiling: bool,
) -> None:
    if not trips:
        logger.info("No active trips; nothing to do for week %s", week_start)
        return

    per_trip = slots_per_trip_per_week(settings)
    budget = per_trip * len(trips)
    logger.info(
        "Week %s: %s active trip(s), %s calls planned (cap=%s)",
        week_start,
        len(trips),
        budget,
        settings.max_weekly_routes_calls,
    )
    if enforce_ceiling and budget > settings.max_weekly_routes_calls:
        logger.error(
            "Skipping week %s: planned %s calls exceeds MAX_WEEKLY_ROUTES_CALLS=%s",
            week_start,
            budget,
            settings.max_weekly_routes_calls,
        )
        return

    total_updated = 0
    total_errors = 0

    for trip in trips:
        inserted = _upsert_empty_slots(
            trip_id=trip.id, week_start=week_start, settings=settings
        )
        logger.info(
            "Trip %s (%s): %s empty slots seeded for week %s",
            trip.id,
            trip.name or "(unnamed)",
            inserted,
            week_start,
        )
        stats = _fill_in_slots_for_trip(
            trip=trip, week_start=week_start, provider=provider, settings=settings
        )
        total_updated += stats["updated"]
        total_errors += stats["errors"]
        logger.info(
            "Trip %s: %s slots filled, %s errors", trip.id, stats["updated"], stats["errors"]
        )

    logger.info(
        "Week %s complete: %s slots filled, %s errors across %s trips",
        week_start,
        total_updated,
        total_errors,
        len(trips),
    )


def _filter_out_review_account_trips(
    trips: list[Trip], settings: Settings
) -> list[Trip]:
    """Drop trips whose owner is a configured review account.

    The weekly Monday 01:00 PT cron would otherwise spend ~840 Google
    Maps Routes Matrix calls per reviewer trip every week of the year.
    Reviewer trips don't need a cron refresh — when the reviewer
    actually signs in and creates a trip, the on-create dual-week
    backfill (already routed to FixtureProvider by `backfill_trip_for_week`)
    fills the heatmap synchronously.

    No-op when `review_account_emails` is empty (i.e. local / dev /
    forks without an App Store review configured).
    """
    review_emails = {e.lower() for e in settings.review_account_emails}
    if not review_emails:
        return trips

    keep: list[Trip] = []
    skipped = 0
    for trip in trips:
        owner = get_user_by_id(trip.user_id)
        if owner is not None and owner.email.lower() in review_emails:
            skipped += 1
            continue
        keep.append(trip)
    if skipped:
        logger.info(
            "Cron: skipped %s review-account trip(s) "
            "(saves ~%s Routes Matrix calls).",
            skipped,
            skipped * slots_per_trip_per_week(settings),
        )
    return keep


def main(
    provider: CommuteProvider | None = None,
    settings: Settings | None = None,
) -> None:
    """Weekly cron entry point (Mon 01:00 PT). Refreshes next week's data for every trip."""
    settings = settings or get_settings()
    provider = provider or get_provider(settings)
    trips = _filter_out_review_account_trips(list_active_trips(), settings)
    _plan_and_run(
        trips=trips,
        week_start=next_week_monday(),
        provider=provider,
        settings=settings,
        enforce_ceiling=True,
    )


def backfill_trip_for_week(
    trip_id: int,
    week_start: date,
    provider: CommuteProvider | None = None,
    settings: Settings | None = None,
) -> None:
    """Fill one specific week of one trip's heatmap right now (called from API).

    We intentionally skip the global ceiling here because it's a single
    trip's worth of calls (~840), which is never going to be the problem
    — the Monday fleet-wide run is.

    When the caller doesn't pin a provider, this picks one per-trip via
    the owner's email so that App Store / Play Store reviewer accounts
    transparently get the `FixtureProvider`. The `provider=` kwarg still
    wins when set (tests use it to inject deterministic fakes).
    """
    settings = settings or get_settings()

    with Database() as cursor:
        cursor.execute(
            """
            SELECT id, slug, user_id, name, origin_address, destination_address, created_at
            FROM trips
            WHERE id = %s AND deleted_at IS NULL
            """,
            (trip_id,),
        )
        row = cursor.fetchone()

    if row is None:
        logger.warning(
            "backfill_trip_for_week: trip %s not found (week=%s)",
            trip_id,
            week_start,
        )
        return

    from app.services.trips import Trip as TripModel

    trip = TripModel(
        id=int(row[0]),
        slug=str(row[1]),
        user_id=int(row[2]),
        name=row[3],
        origin_address=row[4],
        destination_address=row[5],
        created_at=row[6],
    )

    if provider is None:
        owner = get_user_by_id(trip.user_id)
        owner_email = owner.email if owner is not None else None
        provider = provider_for_user_email(owner_email, settings)

    _plan_and_run(
        trips=[trip],
        week_start=week_start,
        provider=provider,
        settings=settings,
        enforce_ceiling=False,
    )


def backfill_trip_current_week(
    trip_id: int,
    provider: CommuteProvider | None = None,
    settings: Settings | None = None,
) -> None:
    """Backwards-compatible wrapper that backfills the current week only.

    Prefer `backfill_trip_for_week(trip_id, week_start)` in new code.
    """
    backfill_trip_for_week(
        trip_id, current_week_monday(), provider=provider, settings=settings
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
