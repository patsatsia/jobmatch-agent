import asyncio
import logging
import random
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_USER_AGENT = "jobmatch-agent/0.1"


class HttpClientError(Exception):
    """Base error for all failures raised by HttpClient."""


class HttpStatusError(HttpClientError):
    """The server answered with an error status (after any retries)."""

    def __init__(self, status_code: int, url: str, body: str) -> None:
        self.status_code = status_code
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status_code} for {url}: {body[:200]}")


class HttpTransportError(HttpClientError):
    """Network-level failure (timeout, connection refused, ...) after all retries."""


class HttpClient:
    """Async HTTP client with retries, backoff, rate limiting and request logging."""

    def __init__(
        self,
        base_url: str = "",
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 10.0,
        min_interval: float = 0.0,
        headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        Args:
            base_url: Prefix for relative URLs.
            timeout: Seconds before a single attempt is abandoned.
            max_retries: Extra attempts after the first one (0 = no retries).
            backoff_base: First retry waits about this many seconds, then doubles.
            backoff_max: Upper bound for a single wait.
            min_interval: Minimum seconds between requests (be polite to free APIs).
            headers: Extra default headers.
            transport: Inject a custom transport (tests use httpx.MockTransport).
        """
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._min_interval = min_interval
        self._last_request_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"User-Agent": DEFAULT_USER_AGENT, **(headers or {})},
            transport=transport,
            follow_redirects=True,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response:
        return await self.request("GET", url, params=params)

    async def post(
        self,
        url: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        return await self.request("POST", url, json=json, params=params)

    async def get_json(self, url: str, *, params: Mapping[str, Any] | None = None) -> Any:
        """GET and decode the JSON body. Validate the result with Pydantic at the call site."""
        response = await self.get(url, params=params)
        return response.json()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Send a request, retrying network errors and retryable status codes.

        Raises:
            HttpStatusError: non-2xx response after retries are exhausted
                (non-retryable codes like 400/404 fail immediately).
            HttpTransportError: network failure after retries are exhausted.
        """
        attempts = self._max_retries + 1
        for attempt in range(1, attempts + 1):
            await self._wait_for_rate_limit()
            started = time.perf_counter()
            try:
                response = await self._client.request(method, url, params=params, json=json)
            except httpx.TransportError as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000
                if attempt == attempts:
                    logger.error("%s %s failed after %d attempts: %r", method, url, attempt, exc)
                    raise HttpTransportError(f"{method} {url} failed: {exc!r}") from exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "%s %s network error on attempt %d/%d after %.0f ms (%r), retrying in %.2fs",
                    method,
                    url,
                    attempt,
                    attempts,
                    elapsed_ms,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s %s -> %d in %.0f ms (attempt %d/%d)",
                method,
                response.request.url,
                response.status_code,
                elapsed_ms,
                attempt,
                attempts,
            )

            if response.is_success:
                return response

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts:
                delay = self._retry_after(response) or self._backoff_delay(attempt)
                logger.warning(
                    "%s %s got %d, retrying in %.2fs", method, url, response.status_code, delay
                )
                await asyncio.sleep(delay)
                continue

            raise HttpStatusError(response.status_code, str(response.request.url), response.text)

        raise AssertionError("unreachable")  # pragma: no cover

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter: random wait in [0, base * 2^(attempt-1)]."""
        ceiling = min(self._backoff_max, self._backoff_base * 2 ** (attempt - 1))
        return random.uniform(0, ceiling)  # noqa: S311 - not used for security

    def _retry_after(self, response: httpx.Response) -> float | None:
        """Honour a numeric Retry-After header (seconds), capped at backoff_max."""
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return min(float(value), self._backoff_max)
        except ValueError:
            return None  # HTTP-date form: fall back to normal backoff

    async def _wait_for_rate_limit(self) -> None:
        """Keep at least `min_interval` seconds between consecutive requests."""
        if self._min_interval <= 0:
            return
        async with self._rate_lock:
            wait = self._last_request_at + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()
