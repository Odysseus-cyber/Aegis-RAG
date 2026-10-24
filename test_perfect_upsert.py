import hashlib
import time

import chromadb


class Chunk:
    def __init__(self, text: str, doc_name: str, chunk_index: int, section: str):
        self.text = text
        self.doc_name = doc_name
        self.chunk_index = chunk_index
        self.section = section
        self.section_path = f"Root > {section}"
        self.content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]

    @property
    def chroma_id(self) -> str:
        path_hash = hashlib.md5(self.section_path.encode('utf-8')).hexdigest()[:8]
        return f"{self.doc_name}::{path_hash}::{self.content_hash}"

    @property
    def metadata(self) -> dict:
        return {"doc_name": self.doc_name, "section": self.section, "chunk_index": self.chunk_index, "content_hash": self.content_hash}

# 💸 模拟极其昂贵、耗时的大模型 Embedding API (每个 Chunk 耗时 0.5 秒)
def call_expensive_llm_api(text):
    print(f"   [API 调用] 正在为文本生成向量... (耗时 0.5s) -> {text[:15]}...")
    time.sleep(0.5)
    return [0.123] * 768

# --- 愚蠢的暴力入库 (没有 update) ---
def _upsert_chunks_naive(collection, chunks):
    print("\n   [开始暴力 Upsert] 不管新旧，全部重新算向量！")
    # 🚨 灾难发生地：所有 chunks 都要重新调一次大模型 API！
    embeddings = [call_expensive_llm_api(c.text) for c in chunks]
    collection.upsert(
        ids=[c.chroma_id for c in chunks],
        embeddings=embeddings,
        documents=[c.text for c in chunks],
        metadatas=[c.metadata for c in chunks],
    )

# --- 完美的企业级入库 (包含 update 优化) ---
def _upsert_chunks_perfect(collection, chunks):
    current_doc_name = chunks[0].doc_name
    existing_db_data = collection.get(where={"doc_name": current_doc_name})
    existing_db_ids = set(existing_db_data["ids"]) if existing_db_data and existing_db_data["ids"] else set()

    # ✨ 核心分流
    new_chunks = [c for c in chunks if c.chroma_id not in existing_db_ids]
    existing_chunks = [c for c in chunks if c.chroma_id in existing_db_ids]

    print(f"\n   [开始完美逻辑] 发现 {len(new_chunks)} 个新段落，{len(existing_chunks)} 个旧段落。")

    if new_chunks:
        # ✅ 只为真正的新数据调用大模型 API！
        new_embeddings = [call_expensive_llm_api(c.text) for c in new_chunks]
        collection.upsert(
            ids=[c.chroma_id for c in new_chunks],
            embeddings=new_embeddings,
            documents=[c.text for c in new_chunks],
            metadatas=[c.metadata for c in new_chunks],
        )

    if existing_chunks:
        print("   [执行 Update] 极其轻量：跳过大模型，直接刷新数据库 Metadata！")
        collection.update(
            ids=[c.chroma_id for c in existing_chunks],
            metadatas=[c.metadata for c in existing_chunks]
        )

# --- 见证奇迹的对比测试 ---
def run_comparison():
    client = chromadb.EphemeralClient()
    col_naive = client.create_collection("naive_test")
    col_perfect = client.create_collection("perfect_test")

    # 初始状态：三个段落
    v1_chunks = [
        Chunk("Title: Testimony...", "DocA", 0, "S1"),
        Chunk("From Principle to Practice...", "DocA", 1, "S2"),
        Chunk("Conclusion...", "DocA", 2, "S3")
    ]

    print("====== 初始化数据 ======")
    _upsert_chunks_naive(col_naive, v1_chunks)
    _upsert_chunks_perfect(col_perfect, v1_chunks)

    # 剧变发生：中间插入一段，导致后面所有的 index 全部位移
    v2_chunks = [
        Chunk("Title: Testimony...", "DocA", 0, "S1"),
        Chunk("Congressional Leadership...", "DocA", 1, "New_S"), # ✨ 新插队的
        Chunk("From Principle to Practice...", "DocA", 2, "S2"),  # 🚨 被挤到 index 2
        Chunk("Conclusion...", "DocA", 3, "S3")                   # 🚨 被挤到 index 3
    ]

    print("\n\n====== 测试 1：暴力无脑 Upsert (没有 update 优化) ======")
    start = time.time()
    _upsert_chunks_naive(col_naive, v2_chunks)
    print(f"❌ 暴力版耗时: {(time.time() - start):.2f} 秒 (调了 4 次 API)")

    print("\n\n====== 测试 2：企业级完美版 (包含 update 优化) ======")
    start = time.time()
    _upsert_chunks_perfect(col_perfect, v2_chunks)
    print(f"✅ 完美版耗时: {(time.time() - start):.2f} 秒 (只调了 1 次 API！)")

if __name__ == "__main__":
    run_comparison()
