import asyncio

import httpx

from app.main import app


def test_health_smoke() -> None:
    async def check() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/healthz")

    response = asyncio.run(check())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0", "build": "local"}
