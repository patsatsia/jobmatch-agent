from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.http.client import HttpClient
from app.sources.arbeitnow import ArbeitnowClient, ArbeitnowJob, to_job_row


def job_json(slug: str, **overrides: Any) -> dict[str, Any]:
    """One job as Arbeitnow sends it."""
    return {
        "slug": slug,
        "company_name": "Acme GmbH",
        "title": f"Python Developer {slug}",
        "description": "<p>We build things.</p>",
        "remote": True,
        "url": f"https://www.arbeitnow.com/jobs/{slug}",
        "tags": ["Python", "Django"],
        "job_types": ["full time"],
        "location": "Berlin",
        "created_at": 1_794_355_215,
        **overrides,
    }


def page_json(slugs: list[str], next_url: str | None) -> dict[str, Any]:
    return {"data": [job_json(s) for s in slugs], "links": {"next": next_url}}


def fake_api(pages: dict[int, dict[str, Any]], seen: list[httpx.Request]) -> HttpClient:
    """HttpClient whose transport serves `pages` by page number and records requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        page = int(request.url.params["page"])
        return httpx.Response(200, json=pages.get(page, page_json([], None)))

    return HttpClient(transport=httpx.MockTransport(handler), backoff_base=0)


async def test_iter_jobs_follows_pages_until_last() -> None:
    seen: list[httpx.Request] = []
    pages = {
        1: page_json(["a", "b"], next_url="https://www.arbeitnow.com/api/job-board-api?page=2"),
        2: page_json(["c"], next_url=None),
    }
    async with fake_api(pages, seen) as http:
        slugs = [job.slug async for job in ArbeitnowClient(http).iter_jobs()]

    assert slugs == ["a", "b", "c"]
    assert len(seen) == 2


async def test_iter_jobs_respects_max_pages() -> None:
    seen: list[httpx.Request] = []
    pages = {
        1: page_json(["a"], next_url="https://www.arbeitnow.com/api/job-board-api?page=2"),
        2: page_json(["b"], next_url=None),
    }
    async with fake_api(pages, seen) as http:
        slugs = [job.slug async for job in ArbeitnowClient(http).iter_jobs(max_pages=1)]

    assert slugs == ["a"]
    assert len(seen) == 1


async def test_fetch_visa_slugs_uses_the_visa_filter() -> None:
    seen: list[httpx.Request] = []
    pages = {1: page_json(["visa-1", "visa-2"], next_url=None)}
    async with fake_api(pages, seen) as http:
        slugs = await ArbeitnowClient(http).fetch_visa_slugs()

    assert slugs == {"visa-1", "visa-2"}
    assert seen[0].url.params["visa_sponsorship"] == "true"


async def test_invalid_payload_raises_validation_error() -> None:
    seen: list[httpx.Request] = []
    broken = page_json(["a"], next_url=None)
    del broken["data"][0]["title"]
    async with fake_api({1: broken}, seen) as http:
        with pytest.raises(ValidationError):
            await ArbeitnowClient(http).fetch_page(1)


def test_to_job_row_maps_fields() -> None:
    job = ArbeitnowJob.model_validate(job_json("abc", title="  Senior Dev  ", tags=[]))

    row = to_job_row(job, has_visa_sponsorship=True)

    assert row["source"] == "arbeitnow"
    assert row["source_id"] == "abc"
    assert row["title"] == "Senior Dev"
    assert row["company"] == "Acme GmbH"
    assert row["url"] == "https://www.arbeitnow.com/jobs/abc"
    assert row["is_remote"] is True
    assert row["has_visa_sponsorship"] is True
    assert row["tags"] == []
    assert row["posted_at"] == datetime.fromtimestamp(1_794_355_215, tz=UTC)
    assert row["posted_at"].tzinfo is not None
