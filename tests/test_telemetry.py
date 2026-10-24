from __future__ import annotations

import pytest

from app.telemetry import logger as tl
from app.telemetry.schema import Message


@pytest.mark.asyncio
async def test_log_message_returns_id(isolated_db):
    mid = tl.log_message(
        conversation_id="conv-1",
        role="assistant",
        content="Test response",
    )
    assert isinstance(mid, str)
    assert len(mid) > 0


@pytest.mark.asyncio
async def test_log_message_writes_to_db(isolated_db):
    """Background task must actually persist the row to the database."""
    from app.conversation import get_or_create_conversation

    await get_or_create_conversation("conv-db-1")

    mid = tl.log_message(
        conversation_id="conv-db-1",
        role="assistant",
        content="Basel III requires 8% capital.",
        rewritten_query="Basel III capital requirements",
        retrieval_latency_ms=50,
        llm_latency_ms=400,
    )

    await tl.flush_messages()

    async with isolated_db() as session:
        from sqlalchemy import select
        row = (await session.execute(select(Message).where(Message.id == mid))).scalar_one_or_none()

    assert row is not None, "log_message background task did not write to DB"
    assert row.content == "Basel III requires 8% capital."
    assert row.rewritten_query == "Basel III capital requirements"
    assert row.retrieval_latency_ms == 50


@pytest.mark.asyncio
async def test_log_message_accepts_optional_fields(isolated_db):
    mid = tl.log_message(
        conversation_id="conv-2",
        role="user",
        content="What is Basel III?",
        rewritten_query="Basel III requirements",
        retrieved_chunks=[{"chunk_id": "abc", "score": 0.9, "doc_name": "doc1", "section": "Intro"}],
        retrieval_latency_ms=120,
        llm_latency_ms=800,
        pii_entities=[],
    )
    assert mid is not None
