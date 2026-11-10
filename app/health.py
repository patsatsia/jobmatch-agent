import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionDep

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])

DB_CHECK_TIMEOUT_SECONDS = 2


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "down"]


@health_router.get("/health")
async def health_check(session: SessionDep, response: Response) -> HealthResponse:
    try:
        async with asyncio.timeout(DB_CHECK_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        logger.exception("Health check: database unreachable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", db="down")

    return HealthResponse(status="ok", db="ok")
