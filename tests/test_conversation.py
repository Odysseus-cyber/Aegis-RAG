from __future__ import annotations

import pytest

from app.conversation import get_conversation_history, get_or_create_conversation


@pytest.mark.asyncio
async def test_create_conversation():
    cid = "test-conv-1"
    result = await get_or_create_conversation(cid, doc_filter=None)
    assert result == cid


@pytest.mark.asyncio
async def test_create_conversation_with_doc_filter():
    cid = "test-conv-scoped"
    await get_or_create_conversation(cid, doc_filter=["doc_a", "doc_b"])
    # Second call should be a no-op and not raise
    result = await get_or_create_conversation(cid, doc_filter=["doc_a", "doc_b"])
    assert result == cid


@pytest.mark.asyncio
async def test_get_empty_history():
    cid = "test-conv-2"
    await get_or_create_conversation(cid)
    history = await get_conversation_history(cid)
    assert history == []
