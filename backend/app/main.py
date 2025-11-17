"""
FastAPI application to expose commute data as an API.
Returns data in the same format used for plotting heatmaps.
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped,import]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped,import]

from app.api.healthcheck_api import healthcheck_router
from app.api.traffic_api import traffic_router
from app.job.data_gathering import main as data_gathering_main  # type: ignore[import-untyped]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Suppress pandas warning about mysql-connector compatibility
warnings.filterwarnings(
    "ignore",
    message=".*SQLAlchemy connectable.*",
    category=UserWarning,
    module="pandas",
)

# Configure scheduler with Pacific Time (handles PST/PDT automatically)
pacific_tz = ZoneInfo("America/Los_Angeles")
scheduler = AsyncIOScheduler(timezone=pacific_tz)


def run_data_gathering():
    """Wrapper function to run data gathering (synchronous function)."""
    logger.info("🔄 Starting data gathering job...")
    start_time = datetime.utcnow()
    try:
        data_gathering_main()
        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"✅ Data gathering job completed successfully in {duration:.2f} seconds"
        )
    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.error(
            f"❌ Error running data gathering job after {duration:.2f} seconds: {e}",
            exc_info=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage scheduler lifecycle."""
    # Startup: schedule the job
    job = scheduler.add_job(
        run_data_gathering,
        trigger=CronTrigger(day_of_week="fri", hour=23, minute=0, timezone=pacific_tz),
        id="weekly_commute_data_gathering",
        replace_existing=True,
    )
    scheduler.start()
    next_run = job.next_run_time
    logger.info(
        f"✅ Scheduler started: Data gathering scheduled for Fridays at 11:00 PM Pacific Time"
        f" (next run: {next_run.isoformat() if next_run else 'N/A'})"
    )
    yield
    # Shutdown: stop the scheduler
    scheduler.shutdown()
    logger.info("✅ Scheduler stopped")


app = FastAPI(title="Traffic Commute API", version="1.0.0", lifespan=lifespan)

app.include_router(healthcheck_router)
app.include_router(traffic_router)

if os.getenv("DEVELOPMENT_MODE") == "prod":
    allowed_origins = "https://traffic.larsjohansen.com"
else:
    allowed_origins = "http://traffic.larsjohansen.com:5173"

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[allowed_origins],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
