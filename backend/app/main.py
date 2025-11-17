"""
FastAPI application to expose commute data as an API.
Returns data in the same format used for plotting heatmaps.
"""

import os
from contextlib import asynccontextmanager
import warnings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped,import]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped,import]

from app.api.healthcheck_api import healthcheck_router
from app.api.traffic_api import traffic_router
from app.job.data_gathering import main as data_gathering_main  # type: ignore[import-untyped]

# Suppress pandas warning about mysql-connector compatibility
warnings.filterwarnings(
    "ignore",
    message=".*SQLAlchemy connectable.*",
    category=UserWarning,
    module="pandas",
)

scheduler = AsyncIOScheduler()


def run_data_gathering():
    """Wrapper function to run data gathering (synchronous function)."""
    try:
        data_gathering_main()
    except Exception as e:
        print(f"❌ Error running data gathering job: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage scheduler lifecycle."""
    # Startup: schedule the job
    scheduler.add_job(
        run_data_gathering,
        trigger=CronTrigger(day_of_week="fri", hour=23, minute=0),
        id="weekly_commute_data_gathering",
        replace_existing=True,
    )
    scheduler.start()
    print("✅ Scheduler started: Data gathering scheduled for Fridays at 23:00")
    yield
    # Shutdown: stop the scheduler
    scheduler.shutdown()
    print("✅ Scheduler stopped")


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
