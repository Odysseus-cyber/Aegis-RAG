import hashlib
import time

import chromadb

# 1. 导入你项目里现有的真实类和函数
from app.rag.chunking import Chunk
from app.rag.ingest import _upsert_chunks


# --- 新增：专门为了适配真实源码的“造数据工厂” ---
def create_chunk(text: str, doc_name: str, chunk_index: int, section: str = "Default Section") -> Chunk:
    """自动补全缺失的 5 个关键参数，生成符合项目规范的 Chunk 实例"""
    # 模拟真实系统生成内容哈希值
    content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    # 模拟真实系统记录入库时间
    ingested_at = str(time.time())

    return Chunk(
        text=text,
        doc_name=doc_name,
        chunk_index=chunk_index,
        doc_title=doc_name.replace("-", " "),  # 简单模拟一下标题
        section=section,
        section_path=f"Root > {section}",      # 简单模拟一下章节路径
        ingested_at=ingested_at,
        content_hash=content_hash
    )

def run_real_test():
    # 2. 启动 ChromaDB 内存模式（绝对不会弄脏你的真实本地数据库）
    client = chromadb.EphemeralClient()
    collection = client.create_collection("test_compliance_real")

    doc_name = "Testimony-John-Zecca-HSFC-03-25-26"

    # 构造假向量（因为 _upsert_chunks 需要向量列表，长度与 chunks 一致即可）
    def make_fake_embeddings(n):
        return [[0.123] * 768 for _ in range(n)]

    print("=== 阶段 1：首次入库 (Initial Ingestion) ===")
    v1_chunks = [
        create_chunk("Title: Testimony of John Zecca...", doc_name, 0, "Title Section"),
        create_chunk("From Principle to Practice: Nasdaq’s Tokenization Framework...", doc_name, 1, "Framework Section"),
        create_chunk("Conclusion...", doc_name, 2, "Conclusion Section")
    ]
    upserted, skipped = _upsert_chunks(collection, v1_chunks, make_fake_embeddings(len(v1_chunks)))
    print(f"✅ 首次入库结果: 写入 {upserted} 块，跳过 {skipped} 块。")
    print(f"   当前真实生成的 Chroma ID:\n   {collection.get()['ids']}\n")

    print("=== 阶段 2：复现【瀑布效应】 (插入新段落) ===")
    v2_chunks = [
        create_chunk("Title: Testimony of John Zecca...", doc_name, 0, "Title Section"),
        create_chunk("Congressional Leadership and the CLARITY Act...", doc_name, 1, "Clarity Act Section"), # ✨ 新增内容
        create_chunk("From Principle to Practice: Nasdaq’s Tokenization Framework...", doc_name, 2, "Framework Section"), # 🚨 Index 变成了 2
        create_chunk("Conclusion...", doc_name, 3, "Conclusion Section") # 🚨 Index 变成了 3
    ]
    upserted, skipped = _upsert_chunks(collection, v2_chunks, make_fake_embeddings(len(v2_chunks)))
    print(f"❌ 瀑布效应触发: 写入 {upserted} 块，跳过 {skipped} 块。")
    print("   【分析】明明只新增了 1 块，却写入了 3 块！\n   因为真实的 chroma_id 依赖了 chunk_index，导致后面所有无辜章节的 ID 全变了！\n")

    print("=== 阶段 3：复现【幽灵数据】 (删除文档结尾) ===")
    v3_chunks = [
        create_chunk("Title: Testimony of John Zecca...", doc_name, 0, "Title Section"),
        create_chunk("Congressional Leadership and the CLARITY Act...", doc_name, 1, "Clarity Act Section"),
        create_chunk("From Principle to Practice: Nasdaq’s Tokenization Framework...", doc_name, 2, "Framework Section"),
        # 🚨 Conclusion 章节被彻底删除了，此时只剩下 3 个 Chunk
    ]
    upserted, skipped = _upsert_chunks(collection, v3_chunks, make_fake_embeddings(len(v3_chunks)))
    print(f"⚠️ 删除后入库: 写入 {upserted} 块，跳过 {skipped} 块。")

    # 不依赖 metadata，直接扫全表来查看幽灵数据
    db_data = collection.get()
    db_texts = db_data["documents"]
    print(f"\n❌ 幽灵数据暴露: 我们明明已经删除了 Conclusion，但此时数据库里共有 {len(db_texts)} 条记录！")

    # 验证 Conclusion 是否依然像幽灵一样存在
    ghost_found = any(txt and "Conclusion" in txt for txt in db_texts)
    if ghost_found:
        print("   【分析】致命错误：数据库中依然残留着 'Conclusion...' 的文本！")
        print("   现有的 _upsert_chunks 完全没有 delete(删) 的逻辑！")
        print("   当 RAG 检索时，大模型依然会读到这段被废弃的合规条款！")

if __name__ == "__main__":
    run_real_test()
