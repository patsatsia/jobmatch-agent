import argparse
import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.session import build_engine, build_sessionmaker
from app.http.client import HttpClient
from app.logging_config import setup_logging
from app.models.jobs import Job
from app.sources.arbeitnow import ArbeitnowClient, to_job_row
from app.utils.text import html_to_text

logger = logging.getLogger(__name__)

BATCH_SIZE = 100

UPDATABLE_COLUMNS = (
    "title",
    "company",
    "location",
    "url",
    "is_remote",
    "has_visa_sponsorship",
    "tags",
    "job_types",
    "posted_at",
    "description_html",
    "description_text",
)


@dataclass
class IngestResult:
    jobs: int = 0
    with_visa: int = 0
    duplicates: int = 0


async def upsert_jobs(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> None:
    """Insert new jobs and update existing ones in a single statement."""
    if not rows:
        return
    stmt = insert(Job).values(list(rows))
    stmt = stmt.on_conflict_do_update(
        index_elements=[Job.source, Job.source_id],
        set_={
            **{column: stmt.excluded[column] for column in UPDATABLE_COLUMNS},
            # Bulk statements skip the model's `onupdate`, so set it explicitly.
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)


async def ingest_arbeitnow(
    sessionmaker: async_sessionmaker[AsyncSession],
    client: ArbeitnowClient,
    *,
    max_pages: int,
) -> IngestResult:
    """Fetch all jobs (and which ones sponsor visas) and upsert them in batches."""
    result = IngestResult()

    visa_slugs = await client.fetch_visa_slugs(max_pages=max_pages)
    logger.info("Found %d jobs with visa sponsorship", len(visa_slugs))

    batch: list[dict[str, Any]] = []
    seen: set[str] = set()
    async for job in client.iter_jobs(max_pages=max_pages):
        # Pages shift while we read them (new jobs push others down), so the same
        # posting can appear twice. Postgres also rejects a batch that upserts
        # the same key twice ("cannot affect row a second time"), so skip repeats.
        if job.slug in seen:
            result.duplicates += 1
            continue
        seen.add(job.slug)

        row: dict[str, Any] = dict(to_job_row(job, has_visa_sponsorship=job.slug in visa_slugs))
        row["description_text"] = html_to_text(row["description_html"])
        batch.append(row)
        result.jobs += 1
        result.with_visa += row["has_visa_sponsorship"]

        if len(batch) >= BATCH_SIZE:
            await _save(sessionmaker, batch)
            batch = []

    await _save(sessionmaker, batch)
    return result


async def _save(
    sessionmaker: async_sessionmaker[AsyncSession], batch: Sequence[dict[str, Any]]
) -> None:
    """One transaction per batch: a failure later on keeps the batches already saved."""
    if not batch:
        return
    async with sessionmaker() as session:
        await upsert_jobs(session, batch)
        await session.commit()
    logger.info("Saved batch of %d jobs", len(batch))


async def main(max_pages: int) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    started = time.perf_counter()
    try:
        async with HttpClient(min_interval=1.0) as http:
            result = await ingest_arbeitnow(
                sessionmaker, ArbeitnowClient(http), max_pages=max_pages
            )
    finally:
        await engine.dispose()

    logger.info(
        "Ingested %d unique jobs (%d with visa sponsorship, %d duplicates skipped) in %.1fs",
        result.jobs,
        result.with_visa,
        result.duplicates,
        time.perf_counter() - started,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest job postings from Arbeitnow.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum pages to fetch per walk (default: 5)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args().max_pages))
