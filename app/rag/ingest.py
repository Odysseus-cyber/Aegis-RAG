from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

import chromadb
import ollama

from app.config import settings
from app.rag.chunking import Chunk, ExtractedDoc, chunk_doc, extract_doc

logger = logging.getLogger(__name__)

# Module-level cached Ollama client — respects settings.ollama_base_url
_ollama_client: ollama.Client | None = None


def _get_ollama_client() -> ollama.Client:
    """Return a cached Ollama sync client.

    Returns:
        A shared ollama.Client instance configured with settings.ollama_base_url.
    """
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = ollama.Client(host=settings.ollama_base_url)
    return _ollama_client


# ---------------------------------------------------------------------------
# ChromaDB client
# ---------------------------------------------------------------------------

def _chroma_client() -> chromadb.ClientAPI:
    """Return a ChromaDB client using settings.

    Uses PersistentClient when CHROMA_MODE=local (default for dev),
    or HttpClient when CHROMA_MODE=http (Docker/K8s).

    Returns:
        A configured chromadb ClientAPI instance.
    """
    if settings.chroma_mode == "local":
        return chromadb.PersistentClient(path=settings.chroma_local_path)
    kwargs: dict = {"host": settings.chroma_host, "port": settings.chroma_port}
    if settings.chroma_auth_token:
        kwargs["headers"] = {"Authorization": f"Bearer {settings.chroma_auth_token}"}
    return chromadb.HttpClient(**kwargs)


def _get_collection(client: chromadb.ClientAPI) -> chromadb.Collection:
    """Get or create the compliance docs collection.

    Args:
        client: An active ChromaDB client.

    Returns:
        The ChromaDB Collection object.
    """
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using nomic-embed-text via Ollama.

    Args:
        texts: List of strings to embed.

    Returns:
        List of float vectors, one per input text.
    """
    response = _get_ollama_client().embed(model=settings.embed_model, input=texts)
    return response.embeddings


# ---------------------------------------------------------------------------
# llms-txt generation
# ---------------------------------------------------------------------------

def _write_llms_txt(extracted: ExtractedDoc, doc_name: str, pipeline_version: str) -> None:
    """Write a clean llms-txt markdown artifact for an ingested document.

    Args:
        extracted: Parsed document content.
        doc_name: Canonical document stem name.
        pipeline_version: Git SHA or 'local'.
    """
    from datetime import datetime, timezone

    out_dir = Path(settings.llms_txt_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_name}.md"

    ingested_at = datetime.now(timezone.utc).isoformat()
    lines: list[str] = [
        "---",
        f"title: {extracted.title}",
        "source: local",
        f"ingested_at: {ingested_at}",
        f"pipeline_version: {pipeline_version}",
        "---",
        "",
    ]
    for heading, _path, body in extracted.sections:
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(body)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote llms-txt artifact: %s", out_path)


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def _upsert_chunks(
    collection: chromadb.Collection,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> tuple[int, int]:
    """Write new chunks, refresh metadata, then remove obsolete chunks for this PDF.

    Return the number of newly written chunks and metadata-only updates.
    """
    if not chunks:
        return 0, 0
    if len(chunks) != len(embeddings):
        raise ValueError("Embedding count does not match chunk count")

    existing_data = collection.get(where={"doc_name": chunks[0].doc_name})
    existing_ids = set(existing_data["ids"])
    incoming_ids = {chunk.chroma_id for chunk in chunks}
    new_chunks = [(chunk, embedding) for chunk, embedding in zip(chunks, embeddings)
                  if chunk.chroma_id not in existing_ids]
    existing_chunks = [chunk for chunk in chunks if chunk.chroma_id in existing_ids]

    if new_chunks:
        collection.upsert(
            ids=[chunk.chroma_id for chunk, _ in new_chunks],
            embeddings=[embedding for _, embedding in new_chunks],
            documents=[chunk.text for chunk, _ in new_chunks],
            metadatas=[chunk.metadata for chunk, _ in new_chunks],
        )
    if existing_chunks:
        collection.update(
            ids=[chunk.chroma_id for chunk in existing_chunks],
            metadatas=[chunk.metadata for chunk in existing_chunks],
        )
    # Keep previous chunks if a replacement write fails.
    stale_ids = list(existing_ids - incoming_ids)
    if stale_ids:
        collection.delete(ids=stale_ids)
    return len(new_chunks), len(existing_chunks)


# ---------------------------------------------------------------------------
# Per-document ingestion
# ---------------------------------------------------------------------------

def ingest_pdf(pdf_path: Path, collection: chromadb.Collection, pipeline_version: str) -> None:
    """Ingest a single PDF into ChromaDB and write its llms-txt artifact.

    Args:
        pdf_path: Path to the PDF file.
        collection: Target ChromaDB collection.
        pipeline_version: Git SHA or 'local'.

    Raises:
        RuntimeError: If the PDF yields no extractable text.
    """
    doc_name = pdf_path.stem
    start = time.monotonic()

    logger.info("Extracting: %s", pdf_path.name)
    extracted = extract_doc(str(pdf_path))

    if not extracted.sections:
        raise RuntimeError(
            f"{pdf_path.name} yielded no extractable text — "
            "likely a scanned image PDF. OCR is not in scope for MVP."
        )

    chunks = chunk_doc(extracted, doc_name=doc_name, pipeline_version=pipeline_version)
    logger.info("Embedding %d chunks for %s", len(chunks), doc_name)
    embeddings = _embed([c.text for c in chunks])

    upserted, skipped = _upsert_chunks(collection, chunks, embeddings)
    _write_llms_txt(extracted, doc_name=doc_name, pipeline_version=pipeline_version)

    elapsed = time.monotonic() - start
    logger.info(
        "Ingested: %s | chunks: %d | skipped: %d | time: %.1fs",
        doc_name, upserted, skipped, elapsed,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Discover all PDFs in data/ and ingest each one. Evaluation runs separately."""
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")

    pipeline_version = _get_pipeline_version()
    data_dir = Path(settings.data_dir)
    pdfs = sorted(data_dir.glob("*.pdf"))

    if not pdfs:
        logger.info("No PDFs found in %s/. Add documents and retry.", data_dir)
        return

    logger.info("Found %d PDF(s) to ingest. Pipeline version: %s", len(pdfs), pipeline_version)

    client = _chroma_client()
    collection = _get_collection(client)

    errors: list[str] = []
    for pdf_path in pdfs:
        try:
            ingest_pdf(pdf_path, collection, pipeline_version)
        except Exception as exc:
            logger.error("%s", exc)
            errors.append(str(exc))

    if errors:
        logger.warning("%d document(s) failed to ingest:", len(errors))
        for e in errors:
            logger.warning("  - %s", e)
        raise RuntimeError("Ingestion failed: " + "; ".join(errors))



def _get_pipeline_version() -> str:
    """Return the short git SHA, or 'local' if not in a git repo.

    Returns:
        Short git SHA string or 'local'.
    """
    if settings.commit_sha not in ("development", "unknown", ""):
        return settings.commit_sha[:12]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "local"


if __name__ == "__main__":
    main()
