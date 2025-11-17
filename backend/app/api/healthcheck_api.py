from fastapi import APIRouter, Response

import app.db.db as db

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
