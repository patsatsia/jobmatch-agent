import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.http.client import HttpClient

logger = logging.getLogger(__name__)

SOURCE = "arbeitnow"
BASE_URL = "https://www.arbeitnow.com"
JOBS_URL = f"{BASE_URL}/api/job-board-api"


class ArbeitnowModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ArbeitnowJob(ArbeitnowModel):
    slug: str
    company_name: str
    title: str
    description: str
    remote: bool
    url: HttpUrl
    tags: list[str] = Field(default_factory=list)
    job_types: list[str] = Field(default_factory=list)
    location: str = ""
    created_at: datetime


class ArbeitnowLinks(ArbeitnowModel):
    next: str | None = None


class ArbeitnowPage(ArbeitnowModel):
    data: list[ArbeitnowJob]
    links: ArbeitnowLinks


class ArbeitnowClient:
    """
    Fetches and validates job postings from Arbeitnow.
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def fetch_page(self, page: int, *, visa_only: bool = False) -> ArbeitnowPage:
        """Fetch and validate one page (pages start at 1)."""
        params: dict[str, Any] = {"page": page}
        if visa_only:
            params["visa_sponsorship"] = "true"
        payload = await self._http.get_json(JOBS_URL, params=params)
        return ArbeitnowPage.model_validate(payload)

    async def iter_jobs(
        self, *, max_pages: int = 5, visa_only: bool = False
    ) -> AsyncIterator[ArbeitnowJob]:
        """Yield jobs page by page until the last page or `max_pages`."""
        for page_number in range(1, max_pages + 1):
            page = await self.fetch_page(page_number, visa_only=visa_only)
            logger.info(
                "Arbeitnow page %d%s: %d jobs",
                page_number,
                " (visa only)" if visa_only else "",
                len(page.data),
            )
            for job in page.data:
                yield job
            if not page.data or page.links.next is None:
                return
        logger.info("Stopped at max_pages=%d; more pages may exist", max_pages)

    async def fetch_visa_slugs(self, *, max_pages: int = 5) -> set[str]:
        """Slugs of jobs that offer visa sponsorship."""
        return {job.slug async for job in self.iter_jobs(max_pages=max_pages, visa_only=True)}


class JobRow(TypedDict):
    source: str
    source_id: str
    title: str
    company: str
    location: str
    url: str
    is_remote: bool
    has_visa_sponsorship: bool
    tags: list[str]
    job_types: list[str]
    posted_at: datetime
    description_html: str


def to_job_row(job: ArbeitnowJob, *, has_visa_sponsorship: bool) -> JobRow:
    return JobRow(
        source=SOURCE,
        source_id=job.slug,
        title=job.title.strip(),
        company=job.company_name.strip(),
        location=job.location.strip(),
        url=str(job.url),
        is_remote=job.remote,
        has_visa_sponsorship=has_visa_sponsorship,
        tags=job.tags,
        job_types=job.job_types,
        posted_at=job.created_at,
        description_html=job.description,
    )
