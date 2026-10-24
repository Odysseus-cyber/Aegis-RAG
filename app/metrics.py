from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

aegis_rag_query_total = Counter(
    "aegis_rag_query_total",
    "Total number of chat queries",
    ["status"],
)

aegis_rag_query_latency_seconds = Histogram(
    "aegis_rag_query_latency_seconds",
    "End-to-end query latency in seconds",
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60],
)

aegis_rag_retrieval_latency_seconds = Histogram(
    "aegis_rag_retrieval_latency_seconds",
    "ChromaDB retrieval latency in seconds",
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2],
)

aegis_rag_llm_latency_seconds = Histogram(
    "aegis_rag_llm_latency_seconds",
    "Time to first token + full stream latency in seconds",
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60],
)

aegis_rag_chunks_retrieved = Histogram(
    "aegis_rag_chunks_retrieved",
    "Number of chunks retrieved per query",
    buckets=[1, 2, 4, 6, 8, 10, 12],
)

aegis_rag_pii_hits_total = Counter(
    "aegis_rag_pii_hits_total",
    "Total PII entities detected and masked",
    ["entity_type"],
)

aegis_rag_conversation_turns = Histogram(
    "aegis_rag_conversation_turns",
    "Number of turns per conversation",
    buckets=[1, 2, 4, 8, 16, 32],
)

aegis_rag_feedback_total = Counter(
    "aegis_rag_feedback_total",
    "Total feedback submissions",
    ["rating"],
)

aegis_rag_drift_breach = Gauge(
    "aegis_rag_drift_breach",
    "1 if the named drift metric breached its threshold, 0 otherwise",
    ["metric_name"],
)
