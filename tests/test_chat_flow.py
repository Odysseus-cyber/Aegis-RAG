from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

import app.main as main
from app.telemetry.schema import Feedback, Message


@pytest.fixture
def pipeline(monkeypatch):
    chunk = {"chunk_id": "c1", "doc_name": "sample", "doc_title": "Sample",
             "section": "Intro", "text": "Grounded text", "score": 0.9}
    monkeypatch.setattr(main, "mask", lambda text: (text.replace("secret@example.com", "<EMAIL_ADDRESS>"), []))
    rewrite = AsyncMock(return_value="standalone query")
    retrieval = AsyncMock(return_value=([chunk], [0.1, 0.2]))
    monkeypatch.setattr(main, "rewrite_query", rewrite)
    monkeypatch.setattr(main, "retrieve", retrieval)

    async def generate(*args):
        yield "A complete "
        yield "answer."

    monkeypatch.setattr(main, "generate_response", generate)
    return rewrite, retrieval


def payload():
    return {"conversation_id": "flow", "message": "Contact secret@example.com",
            "history": [], "doc_filter": ["sample"]}


def events(response):
    return [part for part in response.text.split("\n\n") if part]


async def test_chat_persists_before_done_and_feedback(client, pipeline, isolated_db):
    response = await client.post("/chat", json=payload(), headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    mid = response.headers["X-Message-Id"]
    assert "X-Message-Id" in response.headers["access-control-expose-headers"]
    assert events(response)[0].startswith("event: citations")
    assert events(response)[-1] == 'event: done\ndata: {}'
    pipeline[1].assert_awaited_once_with("standalone query", doc_filter=["sample"])
    history = (await client.get("/conversations/flow")).json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "Contact <EMAIL_ADDRESS>"
    assert history[1]["id"] == mid
    assert history[1]["content"] == "A complete answer."
    feedback = await client.post("/feedback", json={"message_id": mid, "rating": 1})
    assert feedback.status_code == 200
    async with isolated_db() as session:
        row = (await session.execute(select(Feedback))).scalar_one()
        assert row.message_id == mid
        answer = await session.get(Message, mid)
        assert json.loads(answer.retrieved_chunks)[0]["text"] == "Grounded text"


async def test_quality_context_is_masked_before_storage(client, pipeline, isolated_db):
    pipeline[1].return_value[0][0]["text"] = "Contact secret@example.com"
    response = await client.post("/chat", json=payload())
    async with isolated_db() as session:
        answer = await session.get(Message, response.headers["X-Message-Id"])
        assert json.loads(answer.retrieved_chunks)[0]["text"] == "Contact <EMAIL_ADDRESS>"


@pytest.mark.parametrize("stage", ["retrieve", "generate_response", "save_message"])
async def test_stream_failure_never_emits_done(client, pipeline, monkeypatch, stage):
    if stage == "generate_response":
        async def fail(*args, **kwargs):
            yield "Partial answer"
            raise ConnectionError("offline")
        monkeypatch.setattr(main, stage, fail)
    elif stage == "save_message":
        original = main.save_message
        async def fail(**kwargs):
            if kwargs["role"] == "assistant":
                raise RuntimeError("disk unavailable")
            return await original(**kwargs)
        monkeypatch.setattr(main, stage, fail)
    else:
        monkeypatch.setattr(main, stage, AsyncMock(side_effect=ConnectionError("offline")))
    response = await client.post("/chat", json=payload())
    assert "event: error" in response.text
    assert "event: done" not in response.text
    raw = events(response)[-1].split("data: ", 1)[1]
    assert json.loads(raw)["message"]
    history = (await client.get("/conversations/flow")).json()["messages"]
    assert [m["role"] for m in history] == ["user"]


async def test_unknown_feedback_returns_404(client):
    response = await client.post("/feedback", json={"message_id": "missing", "rating": 1})
    assert response.status_code == 404


async def test_pii_failure_is_http_error(client, monkeypatch):
    def fail(text):
        raise RuntimeError("missing model")
    monkeypatch.setattr(main, "mask", fail)
    response = await client.post("/chat", json=payload())
    assert response.status_code == 503


async def test_ingest_failure_is_http_error(client, monkeypatch):
    import app.rag.ingest as ingest
    def fail():
        raise RuntimeError("embedding failed")
    monkeypatch.setattr(ingest, "main", fail)
    assert (await client.post("/admin/ingest")).status_code == 500
