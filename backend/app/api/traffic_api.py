from fastapi import APIRouter

from typing import Dict, Optional
import warnings
import numpy as np
import pandas as pd  # type: ignore[import]
from fastapi import HTTPException
from mysql.connector import Error  # type: ignore[import-untyped]

from app.db.db import pool  # type: ignore[import-untyped]

# Suppress pandas warning about mysql-connector compatibility
warnings.filterwarnings(
    "ignore",
    message=".*SQLAlchemy connectable.*",
    category=UserWarning,
    module="pandas",
)

traffic_router = APIRouter(prefix="/api/v1", tags=["Traffic Commute API"])


def parse_duration_minutes(val) -> float:
    """Convert "3720s" → 62.0"""
    if isinstance(val, str) and val.endswith("s"):
        try:
            return int(val[:-1]) / 60.0
        except Exception:
            return np.nan
    return np.nan


def get_commute_data_from_db() -> pd.DataFrame:
    """Fetch commute data from MySQL database and return as DataFrame."""
    connection = pool.get_connection()
    try:
        query = """
        SELECT
            date_local,
            local_departure_time,
            departure_time_rfc3339,
            direction,
            distance_meters,
            duration,
            `condition`,
            status_code,
            status_message
        FROM commute_slots
        WHERE duration IS NOT NULL
          AND duration != ''
        ORDER BY departure_time_rfc3339
        """
        df = pd.read_sql(query, connection)  # type: ignore[attr-defined]
        return df
    except Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if connection.is_connected():
            connection.close()


def process_commute_data(df: pd.DataFrame) -> Dict[str, Dict]:
    """Process DataFrame into the same format used for plotting."""
    if df.empty:
        return {}

    # Parse duration to minutes
    df["minutes"] = df["duration"].apply(parse_duration_minutes)
    df = df[df["minutes"].notna()]  # type: ignore[assignment]

    # Parse timestamps
    df["ts"] = pd.to_datetime(df["departure_time_rfc3339"], errors="coerce")
    df = df[df["ts"].notna()]  # type: ignore[assignment]

    # Display-friendly direction labels
    df["direction"] = df["direction"].replace(  # type: ignore[assignment]
        {"H2W": "Home → Work", "W2H": "Work → Home"}
    )

    # Weekday mapping
    weekday_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    df["weekday_num"] = df["ts"].dt.weekday
    df["weekday"] = df["weekday_num"].map(weekday_map)  # type: ignore[arg-type]

    # Time-of-day label as HH:MM
    df["time_hm"] = df["ts"].dt.strftime("%H:%M")

    weekday_order = ["Mon", "Tue", "Wed", "Thu", "Fri"]

    result = {}

    for direction_label in sorted(df["direction"].dropna().unique()):  # type: ignore[attr-defined]
        ddir = df[df["direction"] == direction_label].copy()

        if ddir.empty:
            continue

        # Get date range
        monday = ddir["ts"].dt.date.min()  # type: ignore[attr-defined]
        friday = ddir["ts"].dt.date.max()  # type: ignore[attr-defined]
        date_range = f"{monday:%b. %d} – {friday:%b. %d}"

        # Determine period (Morning or Evening)
        hours = ddir["ts"].dt.hour  # type: ignore[attr-defined]
        period_label = "Morning" if hours.max() <= 14 else "Evening"

        # Create pivot table (median minutes by weekday and time)
        times_sorted = sorted(ddir["time_hm"].unique())  # type: ignore[attr-defined]
        pivot = ddir.pivot_table(
            index="weekday", columns="time_hm", values="minutes", aggfunc="median"
        )
        pivot = pivot.reindex(index=weekday_order, columns=times_sorted)

        # Convert pivot table to nested dict format
        heatmap_data: Dict[str, Dict[str, Optional[float]]] = {}
        for weekday in weekday_order:
            if weekday in pivot.index:
                heatmap_data[weekday] = {}
                for time_hm in times_sorted:
                    if time_hm in pivot.columns:
                        value = pivot.loc[weekday, time_hm]
                        # Convert NaN to None for JSON serialization
                        heatmap_data[weekday][time_hm] = (
                            float(value) if not pd.isna(value) else None
                        )

        result[direction_label] = {
            "period": period_label,
            "date_range": date_range,
            "heatmap_data": heatmap_data,
            "weekdays": weekday_order,
            "times": times_sorted,
        }

    return result


@traffic_router.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Traffic Commute API", "version": "1.0.0"}


@traffic_router.get("/commute/heatmap")
async def get_commute_heatmap_data(
    direction: Optional[str] = None,
):
    """
    Get commute heatmap data in the same format used for plotting.

    Args:
        direction: Optional filter by direction ("Home → Work" or "Work → Home")

    Returns:
        Dictionary with heatmap data organized by direction
    """
    try:
        df = get_commute_data_from_db()
        result = process_commute_data(df)

        # Filter by direction if specified
        if direction:
            if direction not in result:
                raise HTTPException(
                    status_code=404, detail=f"Direction '{direction}' not found"
                )
            return {direction: result[direction]}

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing data: {str(e)}")


@traffic_router.get("/commute/directions")
async def get_directions():
    """Get list of available directions."""
    try:
        df = get_commute_data_from_db()
        result = process_commute_data(df)
        return {"directions": list(result.keys())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
