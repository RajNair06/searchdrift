"""FastAPI application: the control plane.

Run locally:  uv run uvicorn searchdrift.api.app:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from sqlalchemy import text

from searchdrift.config import get_settings
from searchdrift.db import make_engine, make_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: create the connection pool once, share it across all requests.
    engine = make_engine(get_settings().database_url)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    yield
    # Shutdown: close every pooled connection cleanly.
    await engine.dispose()


app = FastAPI(title="SearchDrift", lifespan=lifespan)


@app.get("/health")
async def health(request: Request, response: Response) -> dict[str, str]:
    """200 if the API can reach Postgres, 503 if not.

    Load balancers and orchestrators call endpoints like this to decide
    whether to send traffic to this process.
    """
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # any DB failure means "not healthy"; details go to logs later
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
