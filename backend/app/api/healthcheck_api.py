from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Response, HTTPException

import app.db.db as db

pacific_tz = ZoneInfo("America/Los_Angeles")

healthcheck_router = APIRouter(prefix="/healthcheck", tags=["Healthcheck"])


@healthcheck_router.get("")
async def healthcheck(response: Response):
    with db.Database() as cur:
        cur.execute("SELECT 1;")
        row = cur.fetchone()
        if row is not None:
            response.status_code = 200
            return {"status": "healthy"}
    response.status_code = 500
    return {"status": "unhealthy"}


@healthcheck_router.get("/scheduler")
async def scheduler_status():
    """Check scheduler status and job information."""
    # Import here to avoid circular import
    from app.main import scheduler  # type: ignore[import-untyped]

    if not scheduler.running:
        raise HTTPException(status_code=503, detail="Scheduler is not running")

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })

    return {
        "scheduler_running": scheduler.running,
        "timezone": str(scheduler.timezone),
        "current_time_utc": datetime.utcnow().isoformat(),
        "current_time_pacific": datetime.now(pacific_tz).isoformat(),
        "jobs": jobs,
    }


@healthcheck_router.post("/scheduler/trigger")
async def trigger_data_gathering():
    """Manually trigger the data gathering job (for testing)."""
    # Import here to avoid circular import
    from app.main import scheduler, run_data_gathering  # type: ignore[import-untyped]

    try:
        # Run the job in a background task
        import asyncio
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, run_data_gathering)
        return {
            "status": "triggered",
            "message": "Data gathering job has been triggered",
            "time": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger job: {str(e)}")
