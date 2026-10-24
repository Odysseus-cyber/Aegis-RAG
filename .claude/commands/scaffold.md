---
description: Scaffold the full project structure — backend, frontend, monitoring, infra
---

Bootstrap Aegis-RAG from scratch. Run only once at project start.

## Backend

1. `requirements.txt` with exact pinned versions:
   - `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`
   - `chromadb`, `ollama`
   - `presidio-analyzer`, `presidio-anonymizer`, `spacy` + `en_core_web_sm`
   - `prometheus-fastapi-instrumentator`, `prometheus-client`
   - `pymupdf`
   - `sqlalchemy`, `aiosqlite`
   - `pytest`, `pytest-asyncio`, `httpx`, `ruff`

2. `app/config.py` — pydantic-settings reading:
   - `OLLAMA_BASE_URL`, `LLM_MODEL`, `EMBED_MODEL`
   - `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_AUTH_TOKEN`
   - `TELEMETRY_DB_PATH`, `LOG_LEVEL`, `FRONTEND_ORIGIN`

3. `app/main.py` — FastAPI with:
   - CORS restricted to `FRONTEND_ORIGIN`
   - Prometheus instrumentation
   - Routes: `POST /chat` (SSE), `POST /feedback`, `GET /conversations/{id}`, `POST /admin/ingest`, `GET /health`, `GET /admin/documents`

4. `app/llm.py` — async Ollama streaming client with configurable model

5. `app/pii.py` — Presidio `mask(text: str) -> tuple[str, list[dict]]` returning masked text and found entity types

6. `app/conversation.py` — manage conversation state, persist to SQLite, retrieve history

7. `app/rag/`:
   - `ingest.py` — loop over `data/`, call chunker, embed, upsert Chroma, generate llms-txt
   - `chunking.py` — section-aware chunker preserving headings as context
   - `rewrite.py` — multi-turn query rewriter (last 4 turns → standalone query)
   - `retrieve.py` — Chroma search with optional `doc_filter`, return `[{chunk_id, score, doc_name, section, text}]`
   - `generate.py` — prompt assembly (system + chunks + history + query) + SSE stream

8. `app/telemetry/`:
   - `schema.py` — SQLAlchemy models for all tables in CLAUDE.md schema
   - `logger.py` — awaited `save_message(...)` for chat persistence; retain background helper only for ancillary callers
   - `feedback.py` — `async def record_feedback(...)`

9. `app/metrics.py` — all `aegis_rag_*` Prometheus metrics from CLAUDE.md

## Frontend

1. `cd frontend && npm create vite@latest . -- --template react-ts`
2. `npm install -D tailwindcss postcss autoprefixer && npx tailwindcss init -p`
3. `npm install react-markdown lucide-react clsx` (exact versions, no `^`)
4. `src/types.ts` — `Message`, `Conversation`, `Citation`, `DocumentScope`, `FeedbackRating`
5. `src/lib/api.ts` — streaming fetch wrapper, feedback POST, document list GET
6. `src/hooks/`:
   - `useConversation.ts` — conversation state, scope, localStorage persistence
   - `useStreamingChat.ts` — SSE reader, abort controller, token accumulation
   - `useLocalStorage.ts` — generic typed localStorage hook
7. `src/components/`:
   - `ScopeModal.tsx` — shown on new conversation only; global vs multi-select doc picker
   - `ChatWindow.tsx` — main layout wrapper
   - `MessageList.tsx` — auto-scroll, pause on manual scroll-up, `aria-live="polite"`
   - `MessageInput.tsx` — mobile-aware, `env(safe-area-inset-bottom)`, `enterKeyHint="send"`
   - `CitationCard.tsx` — doc name + section badge, expandable
   - `FeedbackButtons.tsx` — thumbs up/down with server-confirmed acknowledgement and retryable errors
   - `DocumentBadge.tsx` — shows active scope in chat header
8. `index.html` — viewport `width=device-width, initial-scale=1, viewport-fit=cover`
9. `vite.config.ts` — proxy `/api/*` → backend during dev

## Monitoring

1. `monitoring/prometheus.yml` — scrape backend + Pushgateway
2. `monitoring/grafana/provisioning/datasources/` — Prometheus datasource, SQLite plugin datasource
3. `monitoring/grafana/dashboards/app-performance.json` — request rate, latency histograms, error rate, PII hits
4. `monitoring/grafana/dashboards/model-quality.json` — actual score/statistic trends, sample counts, current status, feedback ratio, duration and freshness; separate real and synthetic sources
5. `monitoring/drift_job/requirements.drift.txt` — `ollama`, `chromadb`, `sqlalchemy`, `pydantic-settings`, `numpy`, `scipy` (direct exact pins)
6. `monitoring/drift_job/run_drift.py` — CLI entrypoint with `--trigger`, `--pipeline-version`, `--window-hours` args
7. `monitoring/drift_job/snapshot.py` — freeze nonoverlapping reference samples in sidecar JSON and record their summary in `baseline_snapshots`
8. `monitoring/drift_job/retrieval_drift.py` — SciPy KS test on retrieval scores; 10 valid samples per window
9. `monitoring/drift_job/output_drift.py` — NumPy seeded cosine drift + baseline-binned PSI on response length
10. `monitoring/drift_job/quality_eval.py` — local Ollama JSON rubric, sample at most 10 answers by default, write to `eval_results`; require reference answers for context precision
11. `monitoring/drift_job/feedback_analysis.py` — thumbs ratio trend, surface negative comments

## Infra

1. `Dockerfile` — multi-stage Python, non-root `raguser`, uvicorn entrypoint
2. `Dockerfile.drift` — slim Python, separate drift runtime dependencies, entrypoint `python -m monitoring.drift_job.run_drift`
3. `frontend/Dockerfile` — node build stage + nginx runtime with CSP headers
4. `docker-compose.yml`:
   - Services: `ollama`, `chromadb`, `backend`, `frontend`, `prometheus`, `grafana`, `pushgateway`
   - Drift job as `profiles: [drift]` — run with `docker compose --profile drift run drift-job`
   - All health checks defined
   - Named volumes for ollama weights, chroma data, prometheus data, grafana data
5. `k8s/manifests.yaml` — Namespace, ConfigMap, Secret, Deployments + Services + PVCs for every service
6. `k8s/cronjob-drift.yaml` — CronJob `0 2 * * *`, mounts telemetry PVC writable for embedding backfill and evaluation results
7. `.github/workflows/delivery.yml` — unified Python and frontend checks, configuration validation, multi-architecture builds and a complete GHCR delivery manifest; enforce the 200KB gzip JavaScript budget. Real model evaluation runs against the deployed local stack, not on hosted CI runners.
9. `.env.example`, `.gitignore` (include `data/*.pdf`, `llms-txt/`, `telemetry.db`), `README.md`

After scaffolding: run `/ingest` then `/ship-check`. Fix anything that fails before proceeding.
