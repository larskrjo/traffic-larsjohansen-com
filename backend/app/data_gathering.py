#!/usr/bin/env python3
"""
Wrapper that:
1. Generates next week's weekday commute schedule (15 min intervals)
2. Calls Routes Matrix for each timeslot
3. Updates MySQL database with the results

Database:
  Stores commute data in MySQL database

"""

import os
import time
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from mysql.connector import Error  # type: ignore[import-untyped]
import requests  # type: ignore[import-untyped]

from app.constants.secrets import SECRETS
from app.db.db import Database, pool  # type: ignore[import-untyped]

TZ = ZoneInfo("America/Los_Angeles")
ROUTES_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

HOME = "4585 Thousand Oaks Dr, San Jose, CA 95136"
WORK = "650 California St, San Francisco, CA 94108"

INTERVAL_MINUTES = 15


# -------------------------------------------------------
# Database connection and setup
# -------------------------------------------------------
def get_db_connection():
    """Create and return a MySQL database connection from the pool."""
    try:
        connection = pool.get_connection()
        return connection
    except Error as e:
        raise SystemExit(f"❌ Database connection failed: {e}")


# -------------------------------------------------------
# 1. Generate next-week schedule
# -------------------------------------------------------
def get_next_week_weekdays():
    now = datetime.now(TZ)
    days_ahead = (7 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    next_monday = (now + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return [next_monday + timedelta(days=i) for i in range(5)]


def generate_times(day_dt, start: dtime, end: dtime, interval_minutes=INTERVAL_MINUTES):
    cursor = day_dt.replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    end_dt = day_dt.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)

    while cursor < end_dt:
        yield cursor
        cursor += timedelta(minutes=interval_minutes)


def generate_schedule_db():
    """Generate schedule and insert into database."""
    weekdays = get_next_week_weekdays()
    morning_start, morning_end = dtime(5, 0), dtime(13, 0)
    evening_start, evening_end = dtime(12, 0), dtime(20, 0)

    insert_query = """
    INSERT INTO commute_slots
        (date_local, local_departure_time, departure_time_rfc3339, direction,
         distance_meters, duration, `condition`, status_code, status_message)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        updated_at = CURRENT_TIMESTAMP
    """

    inserted_count = 0
    updated_count = 0

    with Database() as cursor:
        for day in weekdays:
            # Home → Work
            for ts in generate_times(day, morning_start, morning_end, INTERVAL_MINUTES):
                values = (
                    ts.date().isoformat(),
                    ts.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    ts.isoformat(),
                    "H2W",
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                try:
                    cursor.execute(insert_query, values)
                    if cursor.rowcount == 1:
                        inserted_count += 1
                    else:
                        updated_count += 1
                except Error as e:
                    print(f"⚠️  Error inserting slot {ts.isoformat()}: {e}")

            # Work → Home
            for ts in generate_times(day, evening_start, evening_end, INTERVAL_MINUTES):
                values = (
                    ts.date().isoformat(),
                    ts.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    ts.isoformat(),
                    "W2H",
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                try:
                    cursor.execute(insert_query, values)
                    if cursor.rowcount == 1:
                        inserted_count += 1
                    else:
                        updated_count += 1
                except Error as e:
                    print(f"⚠️  Error inserting slot {ts.isoformat()}: {e}")

    print(
        f"✅ Schedule generated: {inserted_count} new slots, {updated_count} existing slots updated"
    )


# -------------------------------------------------------
# 2. Compute Route Matrix for each row
# -------------------------------------------------------
def waypoint(address: str):
    return {"waypoint": {"address": address}}


def call_matrix(api_key, origin, dest, departure_rfc3339):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "duration,distanceMeters,status,condition",
    }
    payload = {
        "origins": [waypoint(origin)],
        "destinations": [waypoint(dest)],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": departure_rfc3339,
    }

    r = requests.post(ROUTES_MATRIX_URL, headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text}"}

    data = r.json()
    if not isinstance(data, list) or not data:
        return {"error": f"Unexpected response: {data}"}

    return data[0]


def update_db_with_results():
    """Fetch slots from database, call API, and update results."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if os.getenv("DEVELOPMENT_MODE") == "prod":
        api_key = SECRETS["google_maps_api_key"]
    if not api_key:
        raise SystemExit("❌ Please set GOOGLE_MAPS_API_KEY environment variable")

    # Fetch slots that need updating (empty status_code or NULL)
    select_query = """
    SELECT id, departure_time_rfc3339, direction
    FROM commute_slots
    WHERE status_code IS NULL OR status_code = ''
    ORDER BY departure_time_rfc3339
    """

    # Get connection for dictionary cursor
    connection = get_db_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(select_query)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        connection.close()

    if not rows:
        print("✅ No slots need updating")
        return

    update_query = """
    UPDATE commute_slots
    SET distance_meters = %s,
        duration = %s,
        `condition` = %s,
        status_code = %s,
        status_message = %s,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = %s
    """

    updated_count = 0
    error_count = 0

    # Use Database context manager for updates
    with Database() as cursor:
        for idx, row in enumerate(rows):
            direction = row["direction"]
            origin = HOME if direction == "H2W" else WORK
            dest = WORK if direction == "H2W" else HOME

            ts = row["departure_time_rfc3339"]
            result = call_matrix(api_key, origin, dest, ts)

            if "error" in result:
                status_code = "ERROR"
                status_message = result["error"]
                distance_meters = None
                duration = None
                condition = None
                error_count += 1
            else:
                distance_meters = result.get("distanceMeters")
                duration = result.get("duration", "")
                condition = result.get("condition", "")
                status = result.get("status", {})
                if isinstance(status, dict):
                    status_code = str(status.get("code", ""))
                    status_message = status.get("message", "")
                else:
                    status_code = str(status)
                    status_message = ""

            values = (
                distance_meters,
                duration if duration else None,
                condition if condition else None,
                status_code if status_code else None,
                status_message if status_message else None,
                row["id"],
            )

            try:
                cursor.execute(update_query, values)
                updated_count += 1
            except Error as e:
                print(f"⚠️  Error updating slot {row['id']}: {e}")
                error_count += 1

            if (idx + 1) % 50 == 0:
                # Note: Database context manager will commit on exit
                # Since pool has autocommit=True, changes are auto-committed
                time.sleep(0.5)

    print(f"✅ Database updated: {updated_count} slots updated, {error_count} errors")


def main():
    generate_schedule_db()
    update_db_with_results()
    print("🎉 Commute sampling completed successfully.")


# -------------------------------------------------------
# MAIN ORCHESTRATION
# -------------------------------------------------------
if __name__ == "__main__":
    main()
