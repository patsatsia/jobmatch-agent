from collections.abc import Callable

import httpx
import pytest

from app.http.client import HttpClient, HttpStatusError, HttpTransportError

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, **kwargs: float) -> HttpClient:
    return HttpClient(
        base_url="https://api.test",
        transport=httpx.MockTransport(handler),
        backoff_base=0,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_get_json_returns_decoded_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["page"] == "2"
        return httpx.Response(200, json={"ok": True})

    async with make_client(handler) as client:
        assert await client.get_json("/items", params={"page": 2}) == {"ok": True}


async def test_sends_user_agent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"].startswith("jobmatch-agent/")
        return httpx.Response(200)

    async with make_client(handler) as client:
        await client.get("/")


async def test_retries_server_errors_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503) if calls < 3 else httpx.Response(200, json=[])

    async with make_client(handler) as client:
        assert await client.get_json("/") == []
    assert calls == 3


async def test_gives_up_after_max_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="boom")

    async with make_client(handler, max_retries=2) as client:
        with pytest.raises(HttpStatusError) as exc_info:
            await client.get("/")
    assert calls == 3  # 1 attempt + 2 retries
    assert exc_info.value.status_code == 500


async def test_does_not_retry_client_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    async with make_client(handler) as client:
        with pytest.raises(HttpStatusError):
            await client.get("/missing")
    assert calls == 1


async def test_retries_network_errors_then_raises_transport_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection refused", request=request)

    async with make_client(handler, max_retries=1) as client:
        with pytest.raises(HttpTransportError):
            await client.get("/")
    assert calls == 2


async def test_honours_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("app.http.client.asyncio.sleep", fake_sleep)
    responses = iter([httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200)])

    async with make_client(lambda request: next(responses)) as client:
        await client.get("/")
    assert waits == [3.0]
