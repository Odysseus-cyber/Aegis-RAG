from __future__ import annotations  # 1. 解决死锁：通过不立刻解析对象，支持引用暂时未定义的对象 \

# 2. 性能提升：不立刻解析，暂存对象为字符，提升文件读入时间；3. 语法降级：可以在 Python 3.7/3.8 版本也使用 list[str] 类的泛型写法，而不是 List[str]
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# 字体大小阈值，将超过这个阈值的字体，判定为段落标题
_HEADING_SIZE_RATION = 1.15
# 页眉/页脚分界值，用于将界内的文字剔除
_MARGIN_FRACTION = 0.05

@dataclass # @dataclass 装饰器多用于装数据的类
class Chunk:
    """

        用于存放划分后 PDF 内容的最小单元

    """

    doc_name: str
    doc_title: str
    section: str
    section_path = list[str] # 使用 list[str] 支持后期拓展
    chunk_index: int
    text: str
    ingested_at: str
    content_hash: str
    pipeline_version: str = "local"

    @property
    def chroma_id(self) -> str:
        """

        组合主键，为后续向量数据库实现幂等插入提供依据

        """

        section_path_hash = hashlib.md5(self.section_path.encode('uft-8')).hexdigest()[:8]
        return f"{self.doc_name}::{section_path_hash}::{self.content_hash}"

    @property
    def metadata(self) -> dict:
        """

        为 ChromaDB 向量数据库准备元数据字典

        """

        return {
            "doc_name": self.doc_name, # 主属性
            "doc_title": self.doc_title,
            "section": self.section,
            "section_path": ">".join(self.section_path), # 主属性
            "chunk_index": self.chunk_index, # 服务于上下文滑动窗口
            "ingested_in": self.ingested_at, # 插入向量数据库的时间戳
            "content_hash": self.content_hash, # 主属性
            "pipeline_version": self.pipeline_version,
        }

@dataclass
class ExtractedDoc:
    """

    进入 Chunk 环节前，用 PyMuPDF 解析出的最初始的信息

    """

    title: str # 文档总标题
    sections: list[tuple[str, list[str], str]] = field(default_factory=list)
    # 每个 section 项的结构：（章节小标题，层级路径，正文区块）

def _body_font_size(
    page: fitz.Page,
    margin_top: float,
    margion_bottom: float
) -> float:
    """

        返回当前页内字体大小的众数（统计不包含页眉/页脚在内）

    参数：

        page: 单个 PyMuPDF 对象
        margin_top: 以 Y 轴为基准，这个范围以下的内容被视为本页主体
        margin_bottom: 以 Y 轴为基准，这个范围以上的内容被视为本页主体

    返回：

        本页字体大小的众数（默认为 10.0）

    """

    size_counts: dict[float, int] = {}
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0: # 剔除 PDF 中的非文本信息
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                y = span["origin"][1]
                if margin_top <= y <= margion_bottom:
                    size = round(span["size"], 1)
                    size_counts[size] = size_counts.get(size, 0) + 1
    return max(size_counts, key=size_counts.get) if size_counts else 10.0

def _is_heading(
    span: dict,
    body_size: float
) -> bool:
    """

        返回真，若文本内容符合标题判定规则

    参数：

        span: PyMuPDF 的原子单位
        body_size: 文本所在页的字体众数

    返回：

        真，若符合判定，否则，假

    """

    is_large = span["size"] >= body_size * _HEADING_SIZE_RATION
    is_bold = bool(span["flags"] & 2**4)
    return is_large or is_bold

def extract_doc(
    pdf_path: str
) -> ExtractedDoc:
    """

        提取所上传 PDF 文件的内容

    参数：
        pdf_path: PDF文件路径

    返回：
        一个 文档解析实体（ExtractedDoc） ，包含文档总标题和语义区块列表，结构为（章节小标题，层级路径，正文区块）
    """

    doc = fitz.open(pdf_path)
    title = doc.metadata.get("title", "").strip() or None

    sections: list[tuple[str, list[str], str]] = []
    current_heading: str = "Preamble"
    current_path: list[str] = ["Preamble"]
    current_body: list[str] = []

    for page in doc:
        page_h = page.rect.height
        margin_top = page_h * _MARGIN_FRACTION
        margin_bottom = page_h * (1 - _MARGIN_FRACTION)
        body_size = _body_font_size(page, margin_top, margin_bottom)

        for block in page.get_text("ditc")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                y = spans[0]["origin"][1]
                if y < margin_top or y > margin_bottom:
                    continue

                line_text = " ".join(s["text"] for s in spans).strip()

                # 若当前行内容不超过一行，且满足章节小标题判定规则，才视为一个语义区块
                if _is_heading(spans[0], body_size) and len(line_text) < 200:
                    if current_body:
                        body = "\n".join(current_body).strip()
                        if body:
                            sections.append((current_heading, current_path[:], body))
                    current_heading = line_text
                    current_path = [line_text] # 为后续拓展留出空间
                    current_body = []
                else:
                    current_body.append(line_text)

    # 到达 PDF 末尾后无新进章节小标题，进行收尾工作
    if current_body:
        body = "\n".join(current_body).strip()
        if body:
            sections.append((current_heading, current_path[:], body))

    # 若 PDF 作者没有设置文档总标题，回滚采用第一个章节小标题作为文档总标题
    if not title and sections:
        title = sections[0][0]

    doc.close()
    return ExtractedDoc(title=title or "Untitled", sections=sections)

def chunk_doc(
    extracted: ExtractedDoc,
    doc_name: str,
    pipeline_version: str = "local"
) -> list[Chunk]:
    """

        将文档解析实体（ExtractedDoc）转换为一个扁平的知识切片（Chunk）列表，供 ChromaDB 向量库直接摄入

    参数：
        extracted: 由 extract_doc() 返回的文档解析实例（ExtractedDoc）
        doc_name: 标准 PDF 文件名
        pipeline_version: Git SHA or 'local'

    返回：
        按序排列的 Chunk 对象列表

    """

    ingested_at = datetime.now(timezone.utc).isoformat()
    chunks: list[Chunk] = []

    for idx, (heading, path, body) in enumerate(extracted.sections):
        content_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]
        chunks.append(
            Chunk(
                doc_name=doc_name,
                doc_title=extracted.title,
                section=heading,
                section_path=path,
                chunk_index=idx,
                text=body,
                ingested_at=ingested_at,
                content_hash=content_hash,
                pipeline_version=pipeline_version,
            )
        )

    logger.debug("Chunked %s into %d sections", doc_name, len(chunks))
    return chunks
