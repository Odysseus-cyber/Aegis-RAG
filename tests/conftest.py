from __future__ import annotations

import pytest
import sqlalchemy.ext.asyncio as sa
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.telemetry import logger as tl
from app.telemetry.schema import Base


@pytest.fixture(autouse=True)
async def isolated_db(tmp_path, monkeypatch):
    engine = sa.create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    factory = sa.async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tl, "_engine", engine)
    monkeypatch.setattr(tl, "_session_factory", factory)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await tl.flush_messages()
    await engine.dispose()


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
