from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.conversation import get_conversation_history, get_or_create_conversation
from app.metrics import (
    aegis_rag_chunks_retrieved,
    aegis_rag_feedback_total,
    aegis_rag_llm_latency_seconds,
    aegis_rag_pii_hits_total,
    aegis_rag_query_latency_seconds,
    aegis_rag_query_total,
    aegis_rag_retrieval_latency_seconds,
)
from app.pii import mask
from app.rag.generate import generate_response
from app.rag.retrieve import retrieve
from app.rag.rewrite import rewrite_query
from app.telemetry.feedback import record_feedback
from app.telemetry.logger import flush_messages, init_db, save_message

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise database tables on startup."""
    await init_db()
    try:
        yield
    finally:
        await flush_messages()


app = FastAPI(title="Aegis-RAG", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Message-Id"],
)

Instrumentator().instrument(app).expose(app)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    conversation_id: str
    history: list[HistoryMessage] = Field(default_factory=list)
    message: str
    doc_filter: list[str] | None = None

    @field_validator("message")
    @classmethod
    def message_length(cls, v: str) -> str:
        if len(v) > settings.max_query_length:
            raise ValueError(f"Message exceeds {settings.max_query_length} characters")
        return v


class FeedbackRequest(BaseModel):
    message_id: str
    rating: int
    comment: str | None = None

    @field_validator("rating")
    @classmethod
    def rating_valid(cls, v: int) -> int:
        if v not in (1, -1):
            raise ValueError("rating must be 1 or -1")
        return v


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict:
    """Identify the deployed build without exposing runtime configuration."""
    return {
        "name": "Aegis-RAG",
        "commit_sha": settings.commit_sha,
        "build_time": settings.build_time,
        "actions_url": settings.actions_url,
    }


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Multi-turn RAG chat endpoint. Streams SSE tokens.

    Args:
        req: ChatRequest with conversation_id, history, message, doc_filter.

    Returns:
        StreamingResponse of text/event-stream SSE events.
    """
    try:
        masked_query, pii_entities = await asyncio.to_thread(mask, req.message)
        history = [
            {"role": m.role, "content": (await asyncio.to_thread(mask, m.content))[0]}
            for m in req.history
        ]
    except Exception as exc:
        logger.exception("PII processing failed")
        raise HTTPException(503, "PII processing unavailable. Run make doctor on the backend.") from exc

    await get_or_create_conversation(req.conversation_id, req.doc_filter)
    await save_message(
        message_id=str(uuid.uuid4()),
        conversation_id=req.conversation_id,
        role="user",
        content=masked_query,
        pii_entities=pii_entities,
    )
    for entity in pii_entities:
        aegis_rag_pii_hits_total.labels(entity_type=entity["entity_type"]).inc()
    message_id = str(uuid.uuid4())

    async def event_stream() -> AsyncGenerator[str, None]:
        stage = "Chat"
        try:
            query_start = time.monotonic()
            stage = "Query rewrite"
            rewritten = await rewrite_query(history, masked_query)

            stage = "Retrieval (check Ollama and ChromaDB)"
            retrieval_start = time.monotonic()
            chunks, query_embedding = await retrieve(rewritten, doc_filter=req.doc_filter)
            retrieval_ms = int((time.monotonic() - retrieval_start) * 1000)

            aegis_rag_retrieval_latency_seconds.observe(retrieval_ms / 1000)
            aegis_rag_chunks_retrieved.observe(len(chunks))

            citations = [
                {
                    "chunk_id": c["chunk_id"],
                    "doc_name": c["doc_name"],
                    "doc_title": c["doc_title"],
                    "section": c["section"],
                    "score": c["score"],
                }
                for c in chunks
            ]
            yield f"event: citations\ndata: {json.dumps(citations)}\n\n"

            stage = "Generation (check Ollama and the configured model)"
            llm_start = time.monotonic()
            full_response: list[str] = []

            async for token in generate_response(masked_query, chunks, history):
                full_response.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"

            llm_ms = int((time.monotonic() - llm_start) * 1000)
            total_ms = int((time.monotonic() - query_start) * 1000)

            aegis_rag_llm_latency_seconds.observe(llm_ms / 1000)
            aegis_rag_query_latency_seconds.observe(total_ms / 1000)

            response_text, _ = await asyncio.to_thread(mask, "".join(full_response))

            # Persist before completion so feedback can immediately reference this row.
            stage = "Saving the answer"
            stored_chunks = []
            for chunk in chunks:
                masked_context, _ = await asyncio.to_thread(mask, chunk["text"])
                stored_chunks.append({
                    "chunk_id": chunk["chunk_id"], "score": chunk["score"],
                    "doc_name": chunk["doc_name"], "section": chunk["section"],
                    "text": masked_context,
                })
            await save_message(
                message_id=message_id,
                conversation_id=req.conversation_id,
                role="assistant",
                content=response_text,
                rewritten_query=rewritten,
                retrieved_chunks=stored_chunks,
                retrieval_latency_ms=retrieval_ms,
                llm_latency_ms=llm_ms,
                query_embedding=query_embedding,
                pii_entities=pii_entities,
            )

            aegis_rag_query_total.labels(status="success").inc()
            yield "event: done\ndata: {}\n\n"
        except asyncio.CancelledError:
            aegis_rag_query_total.labels(status="cancelled").inc()
            raise
        except Exception:
            logger.exception("%s failed", stage)
            aegis_rag_query_total.labels(status="error").inc()
            error = {"message": f"{stage} failed. Check the backend logs and retry."}
            yield f"event: error\ndata: {json.dumps(error)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Message-Id": message_id,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/feedback")
async def feedback(req: FeedbackRequest) -> dict:
    """Record user thumbs up/down for an assistant message.

    Args:
        req: FeedbackRequest with message_id, rating, optional comment.

    Returns:
        Dict with the new feedback row ID.
    """
    try:
        feedback_id = await record_feedback(
            message_id=req.message_id,
            rating=req.rating,
            comment=req.comment,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    aegis_rag_feedback_total.labels(rating=str(req.rating)).inc()
    return {"feedback_id": feedback_id}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict:
    """Return the full message history for a conversation.

    Args:
        conversation_id: UUID of the conversation.

    Returns:
        Dict with conversation_id and messages list.
    """
    messages = await get_conversation_history(conversation_id)
    return {"conversation_id": conversation_id, "messages": messages}


@app.get("/admin/documents")
async def list_documents() -> dict:
    """List all document names currently indexed in ChromaDB.

    Returns:
        Dict with a 'documents' list of unique doc_name strings.
    """
    from app.rag.ingest import _chroma_client, _get_collection

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: _get_collection(_chroma_client()).get(include=["metadatas"]))
    except Exception as exc:
        logger.exception("Document listing failed")
        raise HTTPException(503, "Document store unavailable. Check ChromaDB configuration.") from exc
    names = sorted({m.get("doc_name", "") for m in result["metadatas"] if m.get("doc_name")})
    return {"documents": names}


@app.post("/admin/ingest")
async def trigger_ingest() -> dict:
    """Trigger the ingestion pipeline for all PDFs in data/.

    Returns:
        Dict with status message.
    """
    from app.rag.ingest import main as ingest_main

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, ingest_main)
    except Exception as exc:
        logger.exception("Ingestion failed")
        raise HTTPException(500, "Ingestion failed. Check the backend logs.") from exc
    return {"status": "ingestion complete"}
