"""/health against the real Postgres from compose.yaml (run `docker compose up -d` first)."""

import httpx
from fastapi import FastAPI

from searchdrift.api.app import app, lifespan
from searchdrift.db import make_engine


async def test_health_ok_when_database_is_up():
    # httpx's ASGITransport calls the app in-process (no real network), but it
    # doesn't run startup/shutdown, so we enter the lifespan ourselves.
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


async def test_health_503_when_database_is_down():
    # Point the app at a port where nothing listens: the check must fail
    # cleanly with 503, not crash with a 500.
    broken = FastAPI()
    broken.router.routes.extend(app.router.routes)
    broken.state.engine = make_engine(
        "postgresql+asyncpg://searchdrift:searchdrift@localhost:1/searchdrift"
    )
    transport = httpx.ASGITransport(app=broken)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    await broken.state.engine.dispose()
    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"
