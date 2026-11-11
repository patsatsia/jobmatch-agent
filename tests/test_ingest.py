from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import build_engine, build_sessionmaker
from app.http.client import HttpClient
from app.ingest import ingest_arbeitnow, upsert_jobs
from app.models.jobs import Job
from app.sources.arbeitnow import ArbeitnowClient
from tests.sources.test_arbeitnow import page_json

pytestmark = pytest.mark.integration

SOURCE = "test-source"


def row(source_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "source": SOURCE,
        "source_id": source_id,
        "title": "Python Developer",
        "company": "Acme",
        "location": "Berlin",
        "url": f"https://example.com/{source_id}",
        "is_remote": True,
        "has_visa_sponsorship": False,
        "tags": ["python"],
        "job_types": ["full time"],
        "posted_at": datetime(2026, 11, 1, tzinfo=UTC),
        "description_html": "<p>Hi</p>",
        "description_text": "Hi",
        **overrides,
    }


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    get_settings.cache_clear()
    engine = build_engine(get_settings().database_url)
    sessionmaker = build_sessionmaker(engine)
    async with sessionmaker() as s:
        yield s
        await s.execute(delete(Job).where(Job.source == SOURCE))  # clean up test rows only
        await s.commit()
    await engine.dispose()


async def count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).where(Job.source == SOURCE)) or 0


async def test_upsert_inserts_new_rows(session: AsyncSession) -> None:
    await upsert_jobs(session, [row("a"), row("b")])
    await session.commit()

    assert await count(session) == 2


async def test_upsert_updates_existing_row_instead_of_duplicating(session: AsyncSession) -> None:
    await upsert_jobs(session, [row("a")])
    await session.commit()
    first = await session.scalar(select(Job).where(Job.source == SOURCE))
    assert first is not None
    first_updated_at = first.updated_at

    await upsert_jobs(session, [row("a", title="Senior Python Developer")])
    await session.commit()
    session.expire_all()
    updated = await session.scalar(select(Job).where(Job.source == SOURCE))

    assert await count(session) == 1
    assert updated is not None
    assert updated.title == "Senior Python Developer"
    assert updated.updated_at > first_updated_at
    assert updated.created_at == first.created_at


async def test_ingest_skips_postings_repeated_across_pages(session: AsyncSession) -> None:
    """Pages shift while we read them, so the same posting can show up twice."""
    slugs = {1: ["dup-test-1", "dup-test-2"], 2: ["dup-test-2", "dup-test-3", "dup-test-3"]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("visa_sponsorship"):
            return httpx.Response(200, json=page_json([], None))
        page = int(request.url.params["page"])
        return httpx.Response(
            200, json=page_json(slugs.get(page, []), "next" if page == 1 else None)
        )

    engine = build_engine(get_settings().database_url)
    try:
        async with HttpClient(transport=httpx.MockTransport(handler), backoff_base=0) as http:
            result = await ingest_arbeitnow(
                build_sessionmaker(engine), ArbeitnowClient(http), max_pages=5
            )
        stored = await session.scalar(select(func.count()).where(Job.source_id.like("dup-test-%")))
    finally:
        await session.execute(delete(Job).where(Job.source_id.like("dup-test-%")))
        await session.commit()
        await engine.dispose()

    assert result.jobs == 3
    assert result.duplicates == 2
    assert stored == 3
