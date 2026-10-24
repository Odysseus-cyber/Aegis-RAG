import asyncio
import logging
from pathlib import Path

# 导入项目自带的模块
from app.rag.generate import generate_response
from app.rag.ingest import _chroma_client, _get_collection, _get_pipeline_version, ingest_pdf
from app.rag.retrieve import retrieve
from app.rag.rewrite import rewrite_query

# 简化日志输出
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

async def run_demo():
    print("=== 第一阶段：模拟数据入库 (Ingestion) ===")
    data_dir = Path("data")
    pdfs = list(data_dir.glob("*.pdf"))
    if not pdfs:
        print("请先往 data/ 文件夹里放一个测试用的 PDF 文件！")
        return

    client = _chroma_client()
    collection = _get_collection(client)
    pipeline_version = _get_pipeline_version()

    # 取第一个 PDF 进行入库
    ingest_pdf(pdfs[0], collection, pipeline_version)
    print(f"\n[{pdfs[0].name}] 已入库完成！\n")


    print("=== 第二阶段：模拟用户提问 (Chat Pipeline) ===")
    # 假设这是用户的提问
    # user_query = "请总结这份文档里关于违规处罚的核心条款。"
    user_query = "What is Nasdaq's approach to tokenization according to this document?"
    print(f"User 提问: {user_query}\n")

    # 1. 查询重写 (这里模拟只有单轮对话，没有历史记录)
    print("[1/3] 正在让大模型重写问题，消除歧义...")
    rewritten_query = await rewrite_query(history=[], new_message=user_query)
    print(f"重写后的查询词: {rewritten_query}\n")

    # 2. 向量检索
    print("[2/3] 正在从 ChromaDB 中检索相关文档块...")
    chunks, _ = await retrieve(query=rewritten_query, top_k=3)
    if not chunks:
        print("未检索到相关内容！")
        return
    print(f"找到了 {len(chunks)} 个相关片段。片段预览:")
    for i, c in enumerate(chunks):
        print(f" - [{c['doc_name']} {c['section']}] 相关度: {c['score']:.2f}")

    # 3. 流式生成回答
    print("\n[3/3] 大模型正在思考并流式生成回答 (已开启 PII 自动脱敏)...")
    print("--------------------------------------------------")

    # 模拟历史记录为空
    history = []

    # 迭代获取生成的每一个 Token
    async for token in generate_response(query=rewritten_query, chunks=chunks, history=history):
        # flush=True 确保字是一个个蹦出来的，实现流式效果
        print(token, end="", flush=True)

    print("\n--------------------------------------------------")
    print("\n✅ Demo 运行结束！")

if __name__ == "__main__":
    # 确保本地 Ollama 已经启动，并且拉取了 gemma3:1b 和 nomic-embed-text
    asyncio.run(run_demo())
