from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

import chromadb
import ollama

from app.config import settings
from app.rag.chunking import Chunk, ExtractedDoc, chunk_doc, extract_doc
from app.rag.ingest import _run_post_ingest_drift

logger = logging.getLogger(__name__)

# 模块级 Ollama 客户端缓存，与 settings.ollama_base_url 有关
_ollama_client: ollama.Client | None = None

def _get_ollama_client() -> ollama.Client:
    """

    返回一个缓存的 Ollama 同步客户端

    返回：
        一个用 settings.ollama_base_url 配置的共享 ollama.Client 实例

    """
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = ollama.Client(host=settings.ollama_base_url)
    return _ollama_client

# ---------------------------------------------------------------------------
# ChromaDB 客户端
# ---------------------------------------------------------------------------

def _chroma_client() -> chromadb.Client:
    """

    根据 settings 返回一个 ChromaDB 客户端

    若 CHROMA_MODE = local (默认开发者模式)， 返回本地化持久客户端 PersistentClient，
    或 CHROMA_MODE = http (Docker/K8s)，返回网络请求客户端 HttpClient

    """
    if settings.chroma_mode == "local":
        return chromadb.PersistentClient(path=settings.chroma_local_path)
    kwargs: dict = {"host": settings.chroma_host, "port": settings.chroma_port}
    if settings.chroma_auth_token:
        kwargs["headers"] = {"Authorization": f"Bearer {settings.chroma_auth_token}"}
    return chromadb.HttpClient(**kwargs)

def _get_collection(
    client: chromadb.ClientAPI
) -> chromadb.Collection:
    """

    根据 settings.chroma_collection 获取或创建 chroma 集合

    参数：
        client: 一个激活的 ChromaDB 客户端

    返回：
        创建的 ChromaDB Collection 对象

    """
    return client.get_or_create_collection(
        name = settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed(
    texts: list[str]
) -> list[list[float]]:
    """

    用 nomic-embed-text 模型去 embed 列表中的文本

    参数：
        texts: 一个以文本为 item 的列表

    返回：
        一个以浮点向量为 item 的列表，一个服点向量代表一个文本 item

    """
    response = _get_ollama_client().embed(model=settings.embed_model, input=texts)
    return response.embeddings

# ---------------------------------------------------------------------------
# llms-txt generation
# ---------------------------------------------------------------------------

def _write_llm_txt(
    extracted: ExtractedDoc,
    doc_name: str,
    pipeline_version: str
) -> None:

    """

    相对应每个导入向量数据库的文档，生产一份干净的人工 markdown llms-txt 纯文本文件

    参数：
        extracted: 文档解析对象
        doc_name: 文档在整个系统中的唯一标识名（即剥离路径和后缀的纯文件名）
        pipeline_version: Git SHA or 'local'

    """
    from datetime import datetime, timezone

    out_dir = Path(settings.llms_txt_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_name}.md"

    ingest_at = datetime.now(timezone.utc).isoformat()
    lines: list[str] = [
        "---",
        f"title: {extracted.title}",
        "source: local",
        f"ingested_at: {ingest_at}",
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
    embeddings: list[list[float]]
) -> tuple[int, int]:
    """

    导 chunks 入 ChromaDB, 跳过没有改变的 chunk

    ChromaDB upsert 操作具有幂等性质 - 现有的 IDs 只有当其内容发生变化时，
    才会被覆盖写。我们会在应用层对无效公转操作进行拦截，通过对比 组合 chroma_id 和
    现有 IDs 的哈希值来决定是否需要调用 upsert 方法

    参数：
        collection: 目标存储 ChromaDB 集合
        chunks: 准备 upsert 的 Chunk 对象们
        embeddings: Chunk.text 所对应的 embedding vectors

    返回：
        二元组（upserted_count, skipped_count）

    """

    if not chunks:
        return 0, 0

    current_doc_name = chunks[0].doc_name

    exisiting_db_data = collection.get(where={"doc_name": current_doc_name})
    exisiting_db_ids = set(exisiting_db_data["ids"]) if exisiting_db_data and exisiting_db_data["ids"] else set()

    incoming_ids = set(c.chroma_id for c in chunks)

    # 1. 垃圾回收：删除彻底废弃的旧数据
    stale_ids = list(exisiting_db_data - incoming_ids)
    if stale_ids:
        collection.delete(ids=stale_ids)

    # 2. 分流：挑出完全没见过的新数据
    new_chunks = [(c, e) for c, e in zip(chunks, embeddings) if c.chroma_id not in exisiting_db_ids]

    # 3.分流：挑出库里已经有，但需要刷新 chunk_index 的旧数据
    exisiting_chunks = [c for c in chunks if c.chroma_id in exisiting_db_ids]

    skipped = len(chunks) - len(new_chunks) # 实际上这里不再是完全 skip，而是转为了 update

    # 4. 执行全新入库 (Upsert 包含文本、向量、元数据)
    if new_chunks:
        collection.upsert(
            ids=[c.chroma_id for c, _ in new_chunks],
            embeddings=[e for _, e in new_chunks],
            documents=[c.text for c, _ in new_chunks],
            metadatas=[c.metadata for c, _ in new_chunks],
        )

    # 5. 执行元数据刷新 (Update 只覆盖 Metadata，极度轻量快速)
    if exisiting_chunks:
        collection.update(
            ids=[c.chroma_id for c, _ in exisiting_chunks],
            metadatas=[c.metadata for c, _ in exisiting_chunks],
        )

    return len(new_chunks), skipped


# ---------------------------------------------------------------------------
# 单文件导入
# ---------------------------------------------------------------------------

def ingest_pdf(
    pdf_path: Path,
    collection: chromadb.Collection,
    pipeline_version: str
) -> None:
    """

    导单个 PDF 文档入 ChromaDB 并产生一份对应的审计文档

    参数：
        pdf_path: PDF 文档的路径
        collections: 目标 ChromaDB 存储集合
        pipeline_version: Git SHA 或 'local'

    抛出：
        RuntimeError: 如果 PDF 的内容是无法提取的文字信息

    """
    doc_name = pdf_path.stem
    start = time.monotonic()

    logger.info("Extracting: %s", pdf_path.name)
    extracted = extract_doc(str(pdf_path))

    if not extracted.sections:
        raise RuntimeError(
            f"{pdf_path.name} yielded no extractable text - "
            "likely a scanned image PDF. OCR is not in scope of MVP."
        )

    chunks = chunk_doc(extracted, doc_name=doc_name, pipeline_version=pipeline_version)
    logger.info("Embedding %d chunks for %s", len(chunks), doc_name)
    embeddings = _embed([c.text for c in chunks])

    upserted, skipped = _upsert_chunks(collection, chunks, embeddings)
    _write_llm_txt(extracted, doc_name=doc_name, pipeline_version=pipeline_version)

    elapsed = time.monotonic() - start
    logger.info(
        "Ingested: %s | chunks: %d | skipped: %d | time: %.1fs",
        doc_name, upserted, skipped, elapsed
    )

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    """

    发现数据存放目录下的所有PDF文件，依次导入ChromaDB，然后运行导入后漂移检测

    """

    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")

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
        except RuntimeError as exc:
            logger.error("%s", exc)
            errors.append(str(exc))

    if errors:
        logger.warning("%d document(s) failed to ingest:", len(errors))
        for e in errors:
            logger.warning(" - %s", e)

    _run_post_ingest_drift()

def _get_pipeline_version() -> str:
    """

    如果是 Git 仓库项目，返回 'git SHA'，否则，返回 'local'

    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'local'

