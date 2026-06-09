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


async def test_test_post_endpoint_success():
    async def fake_test_post():
        return {"published": True, "title": "x", "provider_used": "groq"}

    app = build_app(lambda: {"poller_alive": True}, test_post=fake_test_post)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test-post")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["published"] is True


async def test_test_post_endpoint_failure_returns_500():
    async def fake_test_post():
        return {"published": False, "error": "no items"}

    app = build_app(lambda: {"poller_alive": True}, test_post=fake_test_post)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test-post")
        assert resp.status == 500
        data = await resp.json()
        assert data["status"] == "error"


async def test_test_post_endpoint_unavailable():
    app = build_app(lambda: {"poller_alive": True})  # no test_post wired
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test-post")
        assert resp.status == 503


async def test_test_post_secret_blocks_anonymous_call():
    async def fake_test_post():
        return {"published": True, "title": "x", "provider_used": "groq"}

    app = build_app(
        lambda: {"poller_alive": True},
        test_post=fake_test_post,
        test_post_secret="s3cret",
    )
    async with TestClient(TestServer(app)) as client:
        # No header / token -> 401
        resp = await client.get("/test-post")
        assert resp.status == 401

        # Wrong header -> 401
        resp = await client.get(
            "/test-post", headers={"X-Test-Post-Secret": "wrong"}
        )
        assert resp.status == 401

        # Correct header -> 200
        resp = await client.get(
            "/test-post", headers={"X-Test-Post-Secret": "s3cret"}
        )
        assert resp.status == 200

        # Correct query token also works
        resp = await client.get("/test-post?token=s3cret")
        assert resp.status == 200


async def test_health_degraded_when_poller_dead():
    app = build_app(lambda: {"poller_alive": False})
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        assert resp.status == 503
        data = await resp.json()
        assert data["status"] == "degraded"
