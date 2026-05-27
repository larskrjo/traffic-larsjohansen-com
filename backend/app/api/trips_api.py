"""Per-user trip CRUD + heatmap endpoint.

A logged-in user can list, create, read, and delete their own trips and
fetch the heatmap for the current or next week. Creating or
address-editing a trip schedules background backfills for *both*
weeks so the heatmap starts populating immediately instead of waiting
for the weekly Monday cron and so the next-week toggle is available
right away.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user, is_admin, is_review_account
from app.config import Settings, get_settings
from app.services.address_validation import (
    AddressValidator,
    NullAddressValidator,
    get_address_validator,
)
from app.services.trip_mutations import (
    TripMutationQuotaExceededError,
    record_mutation,
)
from app.services.trip_mutations import (
    assert_within_quota as assert_mutation_quota,
)
from app.services.trip_mutations import (
    quota_for_user as mutation_quota_for_user,
)
from app.services.trips import (
    Trip,
    TripNotFoundError,
    TripQuotaExceededError,
    count_trips_for_user,
    create_trip,
    current_week_start,
    get_heatmap_for_trip,
    get_trip_for_user_by_slug,
    is_week_fully_populated,
    list_trips_for_user,
    next_week_start,
    sample_status_for_trip,
    soft_delete_trip,
    update_trip,
)
from app.services.users import User

WeekParam = Literal["current", "next"]

logger = logging.getLogger(__name__)

trips_router = APIRouter(prefix="/api/v1/trips", tags=["Trips"])


class TripOut(BaseModel):
    """Public trip projection. `id` is the 10-hex-char public slug.

    The internal int PK is never serialized — it stays inside the
    backend so we don't leak a sequential count of trips through the
    JSON API or the URL bar.
    """

    id: str
    name: str | None
    origin_address: str
    destination_address: str
    created_at: str | None


class TripCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    origin_address: str = Field(..., min_length=3, max_length=1024)
    destination_address: str = Field(..., min_length=3, max_length=1024)


class TripPatch(BaseModel):
    """All fields optional; omitted fields are left untouched."""

    name: str | None = Field(default=None, max_length=255)
    # Use default=None as "not provided"; callers who want to rename
    # to empty should pass name="" and we'll coerce to None below.
    origin_address: str | None = Field(default=None, min_length=3, max_length=1024)
    destination_address: str | None = Field(
        default=None, min_length=3, max_length=1024
    )
    # Explicit flag for "clear the name" since pydantic treats both
    # omit and null as None and we otherwise can't tell.
    clear_name: bool = False
    # Set true when addresses are swapped; triggers a backfill.
    swap_addresses: bool = False


class QuotaInfo(BaseModel):
    # Trip *count* quota (existing): how many of the user's trip slots are taken.
    used: int
    limit: int
    # Rolling-7-day "billed mutation" quota: trip creates and address-changing
    # patches. The SPA disables the New Trip button + the address fields on the
    # detail page when `mutations_used >= mutations_limit`, and shows a friendly
    # "your next slot opens in N hours" hint based on `mutations_oldest_age_seconds`.
    mutations_used: int
    mutations_limit: int
    mutations_oldest_age_seconds: int | None = None


class BackfillStatus(BaseModel):
    total: int
    ready: int
    percent_complete: float


class TripDetail(TripOut):
    backfill: BackfillStatus


def _trip_to_out(trip: Trip) -> TripOut:
    return TripOut(
        id=trip.slug,
        name=trip.name,
        origin_address=trip.origin_address,
        destination_address=trip.destination_address,
        created_at=trip.created_at.isoformat() if trip.created_at else None,
    )


def _resolve_week(week: WeekParam) -> date:
    return current_week_start() if week == "current" else next_week_start()


def _backfill_for(trip_id: int, week_start: date | None = None) -> BackfillStatus:
    week_start = week_start or current_week_start()
    status_dict = sample_status_for_trip(trip_id, week_start)
    total = status_dict["total"]
    ready = status_dict["ready"]
    percent = (ready / total * 100.0) if total else 0.0
    return BackfillStatus(
        total=total, ready=ready, percent_complete=round(percent, 1)
    )


def _kickoff_backfill(trip_id: int, week_start: date) -> None:
    """Fire a one-off sample fill for `(trip_id, week_start)`.

    Imported lazily so tests / API-only boot paths don't pay the import
    cost of the data-gathering module.
    """
    from app.job.data_gathering import backfill_trip_for_week

    try:
        backfill_trip_for_week(trip_id, week_start)
    except Exception:
        logger.exception(
            "Backfill failed for trip %s week %s", trip_id, week_start
        )


def _enqueue_dual_week_backfill(
    trip_id: int, background_tasks: BackgroundTasks
) -> None:
    """Schedule background backfills for *both* the current and next week.

    Called after a trip create or address-changing edit so the new/edited
    trip immediately participates in the "two weeks always visible"
    invariant the weekly Mon-01:00 cron maintains for everyone else.
    Per-mutation cost: ~1,680 Routes Matrix calls (~$16.80).
    """
    background_tasks.add_task(_kickoff_backfill, trip_id, current_week_start())
    background_tasks.add_task(_kickoff_backfill, trip_id, next_week_start())


def _validate_addresses_or_400(
    pairs: list[tuple[str, str]], validator: AddressValidator
) -> None:
    """Validate each (label, address) pair; raise 400 on the first failure.

    Runs the configured `AddressValidator` — real Geocoding in prod,
    no-op otherwise — so we don't kick off a ~840-call Routes Matrix
    backfill for an address Google doesn't recognize.
    """
    for label, address in pairs:
        result = validator.validate(address)
        if not result.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.reason or f"Invalid {label} address",
            )


def _address_validator_for(user: User, settings: Settings) -> AddressValidator:
    """Pick the validator to use for this user's trip mutation.

    Reviewer accounts skip the Geocoding pre-flight too. The pre-flight
    is cheap (~$0.005/address) but reviewers may legitimately type test
    strings ("address 1", "home", etc.) that Google would reject — and
    the downstream Routes Matrix calls are already FixtureProvider'd,
    so there's no expensive backfill to protect anyway. Letting any
    string through removes a friction point during App Store review.
    """
    if is_review_account(user, settings):
        return NullAddressValidator()
    return get_address_validator(settings)


def _ensure_current_week_backfill(
    trip_id: int, background_tasks: BackgroundTasks
) -> None:
    """If no samples exist for the current week yet, schedule a backfill.

    This catches two cases that otherwise leave the heatmap stuck on
    "Building… 0 / 0 (0%)" forever:

      1. Old trips viewed after a Monday rollover before the weekly cron
         has populated the new week.
      2. Local dev, where the scheduler is disabled so the weekly cron
         never runs at all.

    The underlying backfill is idempotent (ON DUPLICATE KEY for slot
    seeding, skip-if-already-filled for the provider loop), so a
    redundant call when samples already exist is a cheap no-op.
    """
    week_start = current_week_start()
    status_dict = sample_status_for_trip(trip_id, week_start)
    if status_dict["total"] == 0:
        background_tasks.add_task(_kickoff_backfill, trip_id, week_start)


@trips_router.get("", response_model=list[TripOut])
async def list_my_trips(user: User = Depends(get_current_user)) -> list[TripOut]:
    """Return all of the authenticated user's trips, newest first."""
    return [_trip_to_out(t) for t in list_trips_for_user(user.id)]


def _trip_cap_for(user: User, settings: Settings) -> int:
    """Per-user trip cap, with admins getting the elevated `max_trips_per_admin`.

    Single source of truth so the cap shown to the SPA via /quota and
    the cap actually enforced by `create_trip` can never drift apart.
    """
    if is_admin(user, settings):
        return settings.max_trips_per_admin
    return settings.max_trips_per_user


@trips_router.get("/quota", response_model=QuotaInfo)
async def get_my_quota(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> QuotaInfo:
    """Return slot usage *and* rolling-7-day mutation usage for the caller."""
    mq = mutation_quota_for_user(user.id, settings)
    return QuotaInfo(
        used=count_trips_for_user(user.id),
        limit=_trip_cap_for(user, settings),
        mutations_used=mq.used,
        mutations_limit=mq.limit,
        mutations_oldest_age_seconds=mq.oldest_age_seconds,
    )


def _raise_mutation_quota_429(
    exc: TripMutationQuotaExceededError,
) -> HTTPException:
    """Translate the service-layer quota exception to a 429 with Retry-After."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"You've used {exc.used} of {exc.limit} weekly trip changes. "
            "Each trip create or address edit triggers a fresh week of "
            "Google Maps lookups, so we cap edits to keep costs bounded. "
            "Your next slot opens automatically as older edits age out."
        ),
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


@trips_router.post("", response_model=TripDetail, status_code=status.HTTP_201_CREATED)
async def create_my_trip(
    body: TripCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> TripDetail:
    """Create a trip and kick off an async backfill for the current week."""
    origin = body.origin_address.strip()
    destination = body.destination_address.strip()
    if origin.lower() == destination.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin and destination cannot be the same address",
        )

    # Weekly cost cap: refuse before we even pay for the Geocoding pre-flight
    # so an abusive user can't drain the bill by hammering POST.
    try:
        assert_mutation_quota(user.id, settings)
    except TripMutationQuotaExceededError as exc:
        raise _raise_mutation_quota_429(exc) from exc

    # Cheap Geocoding pre-flight so we don't burn ~840 Routes Matrix
    # calls on a garbage address. No-op in dev / with fixture provider,
    # and no-op for review accounts (FixtureProvider downstream means
    # there's no Routes spend to protect).
    _validate_addresses_or_400(
        [("origin", origin), ("destination", destination)],
        _address_validator_for(user, settings),
    )

    try:
        trip = create_trip(
            user_id=user.id,
            name=body.name,
            origin_address=origin,
            destination_address=destination,
            per_user_cap=_trip_cap_for(user, settings),
            total_cap=settings.max_trips_total,
        )
    except TripQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    # Logged after the trip row is committed so a failed create doesn't
    # consume a mutation slot. Wrap broadly because a DB hiccup here
    # shouldn't 500 a successful trip create — better to serve a stale
    # quota than to fail the user-visible action.
    try:
        record_mutation(user_id=user.id, trip_id=trip.id, kind="create")
    except Exception:
        logger.exception(
            "Failed to record trip-creation mutation for user %s trip %s",
            user.id,
            trip.id,
        )

    _enqueue_dual_week_backfill(trip.id, background_tasks)
    return TripDetail(**_trip_to_out(trip).model_dump(), backfill=_backfill_for(trip.id))


@trips_router.get("/{slug}", response_model=TripDetail)
async def get_my_trip(
    slug: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> TripDetail:
    """Return a single trip owned by the caller."""
    try:
        trip = get_trip_for_user_by_slug(slug=slug, user_id=user.id)
    except TripNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found"
        ) from exc
    _ensure_current_week_backfill(trip.id, background_tasks)
    return TripDetail(**_trip_to_out(trip).model_dump(), backfill=_backfill_for(trip.id))


@trips_router.patch("/{slug}", response_model=TripDetail)
async def update_my_trip(
    slug: str,
    body: TripPatch,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> TripDetail:
    """Edit a trip's name or addresses, optionally swapping A↔B.

    Any address change (including a swap) wipes the cached commute
    samples for this trip and re-kicks the backfill — the heatmap
    repopulates from scratch against the new endpoints.
    """
    from app.services.trips import _UNSET

    # Pre-load the current trip so we can decide up-front whether this
    # patch will *actually* change addresses. The mutation quota check
    # and the Geocoding pre-flight should both fire ONLY for true address
    # mutations — a name-only rename is free, by design.
    try:
        current_trip = get_trip_for_user_by_slug(slug=slug, user_id=user.id)
    except TripNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found"
        ) from exc

    if body.swap_addresses:
        # Addresses being swapped are already in the DB (and thus
        # already passed validation when they were first set), so we
        # skip re-validating them here.
        new_origin: str | None = current_trip.destination_address
        new_destination: str | None = current_trip.origin_address
        will_change_addresses = (
            current_trip.origin_address != current_trip.destination_address
        )
        mutation_kind: str = "swap"
    else:
        new_origin = body.origin_address
        new_destination = body.destination_address
        # Compare the candidate values to the DB to determine whether
        # this patch is "billed". Strip whitespace so trailing-newline
        # edits don't trigger a backfill (and a mutation count) for what
        # is effectively the same address.
        origin_changes = (
            body.origin_address is not None
            and body.origin_address.strip() != current_trip.origin_address
        )
        destination_changes = (
            body.destination_address is not None
            and body.destination_address.strip() != current_trip.destination_address
        )
        will_change_addresses = origin_changes or destination_changes
        mutation_kind = "address_change"

    # Cap-check *before* paying for Geocoding when this patch is billed.
    if will_change_addresses:
        try:
            assert_mutation_quota(user.id, settings)
        except TripMutationQuotaExceededError as exc:
            raise _raise_mutation_quota_429(exc) from exc

    if not body.swap_addresses and (
        body.origin_address is not None or body.destination_address is not None
    ):
        to_validate: list[tuple[str, str]] = []
        if (
            body.origin_address is not None
            and body.origin_address.strip() != current_trip.origin_address
        ):
            to_validate.append(("origin", body.origin_address.strip()))
        if (
            body.destination_address is not None
            and body.destination_address.strip()
            != current_trip.destination_address
        ):
            to_validate.append(
                ("destination", body.destination_address.strip())
            )
        if to_validate:
            _validate_addresses_or_400(
                to_validate, _address_validator_for(user, settings)
            )

    try:
        trip, addresses_changed = update_trip(
            trip_id=current_trip.id,
            user_id=user.id,
            name=None if body.clear_name else (body.name if body.name is not None else _UNSET),
            origin_address=new_origin,
            destination_address=new_destination,
        )
    except TripNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if addresses_changed:
        try:
            record_mutation(
                user_id=user.id, trip_id=trip.id, kind=mutation_kind  # type: ignore[arg-type]
            )
        except Exception:
            logger.exception(
                "Failed to record trip mutation for user %s trip %s",
                user.id,
                trip.id,
            )
        _enqueue_dual_week_backfill(trip.id, background_tasks)

    return TripDetail(**_trip_to_out(trip).model_dump(), backfill=_backfill_for(trip.id))


@trips_router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_trip(
    slug: str, user: User = Depends(get_current_user)
) -> None:
    """Soft-delete a trip. Samples stay until the next cleanup."""
    try:
        trip = get_trip_for_user_by_slug(slug=slug, user_id=user.id)
        soft_delete_trip(trip_id=trip.id, user_id=user.id)
    except TripNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found"
        ) from exc


@trips_router.get("/{slug}/heatmap")
async def get_trip_heatmap(
    slug: str,
    week: WeekParam = Query("current"),
    user: User = Depends(get_current_user),
) -> dict:
    """Return the heatmap payload for this trip's current or next week.

    `next_week_available` is included on every response so the SPA can
    decide whether to show the next-week toggle even when the request
    is for the current week.
    """
    try:
        trip = get_trip_for_user_by_slug(slug=slug, user_id=user.id)
    except TripNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found"
        ) from exc
    payload = get_heatmap_for_trip(trip.id, _resolve_week(week))
    payload["next_week_available"] = is_week_fully_populated(
        trip.id, next_week_start()
    )
    return payload


@trips_router.get("/{slug}/backfill-status", response_model=BackfillStatus)
async def get_trip_backfill_status(
    slug: str,
    background_tasks: BackgroundTasks,
    week: WeekParam = Query("current"),
    user: User = Depends(get_current_user),
) -> BackfillStatus:
    """How much of the requested week has been sampled so far.

    For `week=current` we lazily kick off a backfill if no samples
    exist yet (self-healing for old trips after a Monday rollover or
    in local dev where the cron is disabled). For `week=next` we
    deliberately don't auto-backfill — the only legitimate writers
    for next week are the weekly cron and the dual-week kickoff that
    runs at trip create / address-edit time.
    """
    try:
        trip = get_trip_for_user_by_slug(slug=slug, user_id=user.id)
    except TripNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found"
        ) from exc
    if week == "current":
        _ensure_current_week_backfill(trip.id, background_tasks)
    return _backfill_for(trip.id, _resolve_week(week))


__all__ = ["trips_router"]
