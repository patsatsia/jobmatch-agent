from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import get_session


class _UnreachableDatabaseSession:
    async def execute(self, *args: object, **kwargs: object) -> None:
        raise OSError("connection refused")


async def _unreachable_session() -> AsyncIterator[_UnreachableDatabaseSession]:
    yield _UnreachableDatabaseSession()


@pytest.mark.integration
async def test_health_ok_when_database_is_up(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


async def test_health_degraded_when_database_is_down(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_session] = _unreachable_session

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "down"}
