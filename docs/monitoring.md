# Aegis-RAG monitoring

Prometheus records application latency, token and feedback counters; Grafana provisions application performance and model quality dashboards. Metrics use `aegis_rag_*`; dashboard UIDs are `aegis-rag-app-perf` and `aegis-rag-model-quality`. Archive prior monitoring storage before starting a fresh namespace. Historical samples are not relabelled as current-version observations; insufficient history remains an explicit state.

## Run a real evaluation

The backend initializes the existing telemetry schema. The job uses the same `.env` / environment configuration: `TELEMETRY_DB_PATH`, `OLLAMA_BASE_URL`, `LLM_MODEL`, `EMBED_MODEL`, and Chroma settings. `PUSHGATEWAY_URL` enables metric publishing. SQLite must be writable because evaluation results and missing response embeddings are stored there.

```sh
.venv/bin/python -m pip install scipy==1.15.3
.venv/bin/python -m monitoring.drift_job.run_drift --trigger adhoc --report .runtime/reports/drift.json
```

`DRIFT_BASELINE_PATH` defaults to `baseline.json` beside the configured telemetry database. The initial evaluation freezes the seven days immediately preceding the current 24-hour window, including the actual samples and exact boundaries. Subsequent evaluations reuse that snapshot even if historical messages change. Refresh deliberately after accumulating sufficient history or changing embedding models:

```sh
.venv/bin/python -m monitoring.drift_job.snapshot --pipeline-version <deployed-sha>
```

Snapshots and reports contain masked message content; keep them outside the public repository. The snapshot summary uses the existing `baseline_snapshots` table; samples live in the sidecar JSON, with no schema migration. Empty reference data stays explicitly insufficient until a new snapshot is captured. Windows are UTC half-open intervals with no overlap. Sampling seed is 42.

## Statistical and quality checks

- Retrieval KS p-value: alert below `0.01`.
- Response embedding cosine-similarity drop: alert above `0.05`; missing embeddings are generated from saved masked assistant answers in the job, never during chat.
- Response-length PSI: alert above `0.2`, using baseline-derived bins.
- Negative-feedback ratio: alert at twice a nonzero reference rate; when the reference rate is zero, alert at `20%`.

Each statistical comparison requires at least ten valid samples on both sides. The reference self-similarity and current cross-similarity use deterministic sampled pairs. Mixed embedding dimensions raise an execution error and require explicit rebaselining.

Quality evaluation samples at most ten current answers (`DRIFT_QUALITY_SAMPLE_SIZE`). It uses configured local Gemma through Ollama JSON output with temperature zero and a fixed seed. Scores are **local rubric estimates, not equivalent to DeepEval metrics or human assessment**. Faithfulness measures factual support from retrieved original passages; answer relevance measures how directly and completely the question is answered. Alert thresholds remain `0.7` and `0.65`.

New chat records supply masked original source passages in `retrieved_chunks[].text`. For old records the job resolves chunk IDs from the configured Chroma collection. If the source cannot be recovered it skips that record explicitly; an unavailable service or malformed response is an execution error. IDs themselves are never used as evidence.

Context precision is evaluated only for reference-answer datasets supplied through `DRIFT_REFERENCE_DATASET`: a JSON object mapping existing message IDs to nonempty reference answers. Its threshold is `0.6`. Without reference answers it displays insufficient data. Model parsing failures, embedding failures, SQLite write failures, report-write failures and Pushgateway failures return exit code `2`.

## Reports and dashboard semantics

The JSON report includes exact windows, snapshot identity, sample counts, scores, thresholds, errors, duration and model/method details. Status is one of `passed`, `alert`, `insufficient_data`, `error`. Exit `0` means completed (including explicit insufficient-data skips), `1` means a measured alert and `2` means execution error. A model-quality alert is reported; it does not gate application deployment or trigger rollback.

The job uses HTTP PUT to replace its entire Pushgateway group each run, removing stale values. Group `job=aegis_drift,source=real` is isolated from demonstration data. Metrics are:

- `aegis_rag_drift_value{metric_name}`: actual score/statistic, only when available.
- `aegis_rag_drift_status{metric_name}`: 0 passed, 1 alert, 2 insufficient data, 3 execution error.
- `aegis_rag_drift_breach{metric_name}`: only for evaluated comparisons.
- `aegis_rag_drift_samples{metric_name,window}`: current/reference sample counts.
- `aegis_rag_drift_run_timestamp_seconds`, `aegis_rag_drift_run_duration_seconds`: freshness and runtime.

The Grafana Model Quality dashboard separates actual scores, statistics, sample counts and states. Select `real` or `synthetic_demo` explicitly. A missing score is never replaced by a normal-looking zero. If the job cannot reach Pushgateway, the JSON report records that error and the dashboard's evaluation-age panel identifies stale telemetry.

## Isolated demonstration

These fixtures exercise the same statistical evaluators without reading or writing the chat database. Synthetic quality values and the synthetic connection error are clearly marked and are not real model results.

```sh
PUSHGATEWAY_URL=http://127.0.0.1:19091 .venv/bin/python -m monitoring.drift_job.demo --scenario passed --output .runtime/reports/demo-passed.json
PUSHGATEWAY_URL=http://127.0.0.1:19091 .venv/bin/python -m monitoring.drift_job.demo --scenario alert --output .runtime/reports/demo-alert.json
PUSHGATEWAY_URL=http://127.0.0.1:19091 .venv/bin/python -m monitoring.drift_job.demo --scenario insufficient_data --output .runtime/reports/demo-insufficient.json
PUSHGATEWAY_URL=http://127.0.0.1:19091 .venv/bin/python -m monitoring.drift_job.demo --scenario error --output .runtime/reports/demo-error.json
```

Expected exits are `0`, `1`, `0`, `2`. Each command replaces the synthetic group so the dashboard can show successive states. Real data remains untouched.
