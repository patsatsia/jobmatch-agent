from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db.session import build_engine, build_sessionmaker
from app.health import health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = build_engine(settings.database_url, echo=settings.db_echo)
    app.state.sessionmaker = build_sessionmaker(engine)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="JobMatch Agent", lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()
