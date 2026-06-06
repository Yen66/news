from aiohttp.test_utils import TestClient, TestServer

from src.server import build_app


async def test_root_and_health_ok():
    app = build_app(lambda: {"poller_alive": True, "queue_size": 0})
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"

        resp = await client.get("/health")
        assert resp.status == 200
        health = await resp.json()
        assert health["status"] == "ok"
        assert health["queue_size"] == 0


async def test_health_degraded_when_poller_dead():
    app = build_app(lambda: {"poller_alive": False})
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        assert resp.status == 503
        data = await resp.json()
        assert data["status"] == "degraded"
