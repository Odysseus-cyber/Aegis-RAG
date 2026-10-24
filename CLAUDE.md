# Aegis-RAG

A self-hosted, multi-turn RAG application that lets bank employees ask compliance questions across regulatory documents and get cited answers via a mobile-friendly chat UI. Includes a full model-monitoring pipeline: app performance metrics, retrieval quality drift, output quality drift (local Ollama rubric scoring), and user feedback signals — all using open-source tools, no paid services.

## Project goal

Demonstrate the full MLOps lifecycle for a RAG system: ingestion, serving, observability, drift detection, and continuous evaluation. Designed as an evolving portfolio project — the architecture must support adding enhancements (rerankers, hybrid search, agentic tools, A/B testing) without rewrites.

---

## Tech stack (do not deviate without asking)

### Backend
- **Language**: Python 3.11
- **Web framework**: FastAPI
- **LLM**: Gemma 3 1B via Ollama (`gemma3:1b`)
- **Embeddings**: `nomic-embed-text` via Ollama
- **Vector DB**: ChromaDB with metadata filtering
- **PII masking**: Microsoft Presidio
- **Telemetry store**: SQLite (local dev); Postgres-ready SQLAlchemy schema
- **Eval framework**: local Ollama JSON rubric (no API key; not DeepEval-equivalent scores)
- **Drift detection**: SciPy and NumPy (KS, PSI, and cosine comparisons)

### Frontend
- **Build tool**: Vite
- **Framework**: React 18 + TypeScript
- **Styling**: Tailwind CSS
- **Components**: shadcn/ui (copy-paste, no runtime dependency)
- **State**: `useState` / `useReducer` only — no Redux, no Zustand
- **Persistence**: `localStorage` for conversations; cross-device sync is a roadmap item
- **HTTP**: native `fetch` with `ReadableStream` for SSE streaming

### Infra
- **App metrics**: Prometheus + Grafana
- **Drift job scheduler**: explicit CLI and local post-deploy reporting; optional nightly K8s CronJob example
- **CI/CD**: GitHub Actions → GitHub Container Registry (GHCR)
- **Deployment**: Docker Compose (local); Kubernetes manifests (VM/cluster)

Do not introduce LangChain, LlamaIndex, Redux, Arize Phoenix, or any paid service. Plain orchestration shows engineering judgement.

---

## Architecture

```
┌─────────────┐  session scope set once
│  React UI   │  per conversation (modal on new chat)
│  + doc scope│──fetch SSE──────────────────────────┐
└─────────────┘                                     │
                                                    ▼
                                      ┌─────────────────────────┐
                                      │  FastAPI /chat          │
                                      │  doc_filter: str[]|null │
                                      └─────────────────────────┘
                                                    │
                    ┌───────────────────────────────┼──────────────────┐
                    ▼                               ▼                  ▼
              ┌──────────┐                  ┌─────────────┐   ┌──────────────┐
              │  Query   │                  │  Retrieve   │   │  Generate    │
              │  Rewrite │────────────────> │  ChromaDB   │──>│  Ollama      │
              │  (LLM)   │                  │  + metadata │   │  (SSE stream)│
              └──────────┘                  │  filter     │   └──────────────┘
                                            └─────────────┘          │
                                                    │                 │
                                                    └────────┬────────┘
                                                             ▼
                                                 ┌─────────────────────┐
                                                 │  Telemetry logger   │
                                                 │  (awaited commit)   │
                                                 │  SQLite telemetry.db│
                                                 └─────────────────────┘
                                                             │
                         ┌───────────────────────────────────┤
                         ▼                                   ▼
                  ┌────────────┐                   ┌────────────────────┐
                  │ Prometheus │                   │  Drift job         │
                  │ /metrics   │                   │  (explicit CLI     │
                  └────────────┘                   │  + local deploy    │
                         │                         │  + optional cron)  │
                         ▼                         │                    │
                   ┌──────────┐                    │ Ollama rubric      │
                   │ Grafana  │<──drift metrics────│ SciPy/NumPy stats  │
                   │ 2 boards │                    └────────────────────┘
                   └──────────┘
```

---

## Repository layout

```
Aegis-RAG/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── conversation.py
│   ├── pii.py
│   ├── llm.py
│   ├── metrics.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── ingest.py
│   │   ├── chunking.py
│   │   ├── rewrite.py
│   │   ├── retrieve.py
│   │   └── generate.py
│   └── telemetry/
│       ├── __init__.py
│       ├── schema.py
│       ├── logger.py
│       └── feedback.py
├── monitoring/
│   ├── prometheus.yml
│   ├── grafana/
│   │   ├── provisioning/
│   │   │   ├── datasources/
│   │   │   └── dashboards/
│   │   └── dashboards/
│   │       ├── app-performance.json
│   │       └── model-quality.json
│   └── drift_job/
│       ├── run_drift.py              # explicit evaluator; trigger labels cron, ci, adhoc
│       ├── snapshot.py               # freeze disjoint reference window and sample data
│       ├── retrieval_drift.py        # SciPy KS test on retrieval scores
│       ├── output_drift.py           # NumPy cosine drift and response-length PSI
│       ├── quality_eval.py           # local Ollama rubric, reference answers required for precision
│       ├── feedback_analysis.py      # thumbs ratio trend
│       └── requirements.drift.txt   # pinned deps for the drift job container
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatWindow.tsx
│   │   │   ├── MessageList.tsx
│   │   │   ├── MessageInput.tsx
│   │   │   ├── CitationCard.tsx
│   │   │   ├── FeedbackButtons.tsx
│   │   │   ├── DocumentBadge.tsx
│   │   │   └── ScopeModal.tsx        # session scope selector
│   │   ├── hooks/
│   │   │   ├── useConversation.ts
│   │   │   ├── useStreamingChat.ts
│   │   │   └── useLocalStorage.ts
│   │   ├── lib/
│   │   │   └── api.ts
│   │   ├── types.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json             # lockfile — use npm ci, not npm install
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── Dockerfile
├── tests/
│   ├── conftest.py
│   ├── test_pii.py
│   ├── test_rag_eval.py
│   ├── test_conversation.py
│   ├── test_telemetry.py
│   └── test_security.py
├── k8s/
│   ├── manifests.yaml
│   └── cronjob-drift.yaml
├── .devcontainer/
│   ├── Dockerfile                    # python:3.11-slim + Node 24 + pip-tools
│   └── devcontainer.json             # VS Code / Codespaces; postCreateCommand: make setup
├── .claude/
│   ├── agents/                       # Claude Code subagents
│   │   ├── code-reviewer.md
│   │   ├── dependency-reviewer.md
│   │   ├── drift-analyst.md
│   │   ├── mobile-tester.md
│   │   ├── rag-evaluator.md
│   │   └── security-scanner.md
│   └── commands/                     # slash-command skills
│       ├── ingest.md
│       ├── scaffold.md
│       ├── drift-run.md
│       └── ship-check.md
├── .github/
│   └── workflows/
│       └── delivery.yml
├── docs/
│   ├── architecture.md               # multi-turn pipeline, component map
│   ├── ingestion.md                  # PDF → chunk → ChromaDB deep-dive
│   ├── monitoring.md                 # metrics, Grafana, drift detection
│   ├── testing.md                    # test suite structure and fixtures
│   ├── deployment.md                 # Docker Compose, K8s, CI/CD, env vars
│   └── dependencies.md              # pip-compile workflow, npm pinning
├── data/                             # Drop PDFs here — gitignored (PDFs only)
│   ├── .gitkeep
│   └── README.md
├── llms-txt/                         # Generated per ingested doc — gitignored
│   └── .gitkeep
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.drift
├── Makefile                          # dev workflow: setup, run, test, compile-deps
├── pyproject.toml                    # requires-python, ruff config, pytest config
├── requirements.in                   # direct deps — edit this, not requirements.txt
├── requirements.txt                  # pip-compile output — fully pinned + annotated
├── .python-version                   # pyenv pin: 3.11
├── .env.example
└── README.md
```

---

## Document scoping UX

**Session scope is set once per conversation and never reset mid-session.**

On "New conversation," before any message is sent, show `ScopeModal`:
- Header: "Which documents should I search?"
- Option A: **All documents** (default) — global search across everything ingested
- Option B: **Select documents** — multi-select list of ingested doc names with checkboxes
- A "Start" button confirms the choice and dismisses the modal
- The chosen scope is displayed as a persistent badge in the chat header throughout the session

The scope is stored in conversation state (`doc_filter: string[] | null`) and sent with every `/chat` request. `null` = global. The backend passes it as a ChromaDB `where` metadata filter on `doc_name`.

The scope modal only re-appears on a genuinely new conversation (new `conversation_id`). It does not re-appear if the user reloads the page and resumes an existing conversation — the scope is persisted in `localStorage` with the conversation.

---

## Multi-turn pipeline

The `/chat` endpoint accepts `{conversation_id, history: Message[], message: string, doc_filter: string[] | null}`.

1. **Query rewrite**: send last N=4 turns + new message to Ollama with prompt: *"Given this conversation, write a self-contained search query for the latest question. Output only the query."* Store rewritten query in telemetry.
2. **Retrieve**: embed the rewritten query, search ChromaDB with optional `doc_filter`, get top-K=8.
3. **Generate**: assemble system prompt + retrieved chunks + full conversation history + user message. Stream SSE response.
4. **Log**: commit the masked answer and retrieved source text before emitting SSE `done`; persist the user turn before generation.

---

## Multi-document ingestion

`data/` may hold any number of PDFs. The ingestion pipeline:

1. For each PDF: extract text with PyMuPDF, generate `llms-txt/<name>.md` (section-aware clean markdown with metadata header).
2. Chunk by section (not fixed-size). Each chunk carries metadata: `{doc_name, doc_title, section, section_path, chunk_index, ingested_at, content_hash}`.
3. Upsert into ChromaDB. Re-ingestion is idempotent — keyed on `(doc_name, chunk_index, content_hash)`.
4. **Explicit quality reporting**: run `make evaluate-demo` after deployed ingestion and question-answer verification. The reporting job captures a disjoint seven-day reference on its first run, then keeps it frozen. Refresh deliberately with `python -m monitoring.drift_job.snapshot --pipeline-version <sha>` when appropriate; ingestion itself does not imply a quality check.

---

## Telemetry schema

SQLite (Postgres-ready via SQLAlchemy). Never aggregate at write time — always log raw events.

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    doc_filter JSON,                     -- null = global, else list of doc names
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,                  -- 'user' | 'assistant'
    content TEXT NOT NULL,
    rewritten_query TEXT,
    retrieved_chunks JSON,               -- [{chunk_id, score, doc_name, section}]
    retrieval_latency_ms INTEGER,
    llm_latency_ms INTEGER,
    response_length INTEGER,
    response_embedding BLOB,             -- float32 array for output drift
    query_embedding BLOB,                -- for query distribution drift
    pii_entities_found JSON,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE feedback (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id),
    rating INTEGER NOT NULL,             -- 1 = thumbs up, -1 = thumbs down
    comment TEXT,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE eval_results (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id),
    run_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,           -- 'faithfulness' | 'answer_relevance' | 'context_precision'
    score REAL NOT NULL,
    reason TEXT,                         -- LLM judge's reasoning
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE drift_runs (
    id TEXT PRIMARY KEY,
    triggered_by TEXT NOT NULL,          -- 'cron' | 'ci' | 'adhoc'
    pipeline_version TEXT,               -- git SHA of the deploy that triggered it
    run_at TIMESTAMP NOT NULL,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    threshold REAL NOT NULL,
    breached BOOLEAN NOT NULL,
    details JSON
);

CREATE TABLE baseline_snapshots (
    id TEXT PRIMARY KEY,
    pipeline_version TEXT NOT NULL,      -- git SHA
    captured_at TIMESTAMP NOT NULL,
    retrieval_score_p50 REAL,
    retrieval_score_p95 REAL,
    response_length_p50 REAL,
    faithfulness_mean REAL,
    answer_relevance_mean REAL,
    context_precision_mean REAL,
    feedback_thumbsdown_ratio REAL,
    sample_size INTEGER
);
```

---

## Drift monitoring — three layers

### Layer 1: App performance (Prometheus, real-time)

Metrics exposed at `/metrics` — standard FastAPI instrumentation plus custom:
- `aegis_rag_query_total` (counter, label: status)
- `aegis_rag_query_latency_seconds` (histogram)
- `aegis_rag_retrieval_latency_seconds` (histogram)
- `aegis_rag_llm_latency_seconds` (histogram)
- `aegis_rag_chunks_retrieved` (histogram)
- `aegis_rag_pii_hits_total` (counter, label: entity_type)
- `aegis_rag_conversation_turns` (histogram)
- `aegis_rag_feedback_total` (counter, label: rating)
- `aegis_rag_drift_breach` (gauge, label: metric_name) — set by drift job via Prometheus Pushgateway

### Layer 2: Per-event telemetry (SQLite, every request)

Everything in the `messages` table. The raw retrieval scores, response embeddings, and query embeddings are the source of truth for all statistical drift analysis. User messages and masked assistant answers are committed before the stream reports success. Missing response embeddings are backfilled by the drift job.

### Layer 3: Drift detection job

See [monitoring](docs/monitoring.md) for the current implementation and metric contract. The current 24-hour window is compared with a frozen 7-day reference window ending before it. Statistical checks require at least 10 valid samples per window; insufficient data is visible rather than treated as a healthy score.

The job backfills missing answer embeddings in the configured writable SQLite database. Quality evaluation uses real retrieved text and up to 10 answers, judged by local Gemma. Context precision needs a reference answer and runs only for the dedicated evaluation set. Structured reports distinguish pass, alert, insufficient data, and execution error; exit codes are 0, 1 for alerts, and 2 for errors. Metrics include values, sample counts, state, and timestamps.

The unified `.github/workflows/delivery.yml` uses deterministic tests. `make evaluate-demo` runs real evaluation on the local deployed stack. Quality alerts are reports, not deploy or rollback gates. Demonstration scenarios use isolated data.

---

## User feedback flow

Each assistant message has thumbs up / thumbs down buttons in the UI. On click:
1. Frontend POSTs `{message_id, rating, comment?}` to `/feedback`
2. Backend writes to `feedback` table
3. UI shows acknowledged state only after server success; failures remain retryable
4. Feedback ratio feeds into explicitly run drift reports or the optional CronJob as a direct human quality signal

Feedback is treated as a first-class quality signal — it is the only signal that doesn't require an LLM judge to interpret.

---

## Backend coding rules

- Type-hint everything. `from __future__ import annotations` at top of every module.
- No `print` — use `logging`, configured once in `main.py`.
- All config via `config.py` (pydantic-settings). Never hardcode model names, hosts, ports.
- Functions ≤ 40 lines. Docstrings with Args/Returns on all public functions.
- Pydantic models on every endpoint. Reject queries > 1000 chars.
- `/chat` must support SSE streaming.
- CORS restricted to configured frontend origin.
- **Persist messages before reporting success** — await the masked assistant message commit before sending SSE `done`, so immediate feedback can resolve its server ID.
- **PII masking runs before every LLM call**, including retrieved context and conversation history.

## Frontend coding rules

- TypeScript strict mode. No `any` without a justification comment.
- Functional components only.
- Custom hooks for non-trivial state.
- All API calls via `lib/api.ts` — never inline `fetch`.
- Mobile-first Tailwind. Tap targets ≥ 44x44px.
- `react-markdown` for rendering — never `dangerouslySetInnerHTML`.
- `ScopeModal` shown on new conversation only; scope persisted in localStorage with conversation.

## Mobile and browser support

- Chrome, Firefox, Safari, Edge (current + one version back)
- iOS Safari 16+, Chrome Android 10+
- Viewport meta with `viewport-fit=cover`
- Chat input clear of iOS keyboard (`env(safe-area-inset-bottom)`)
- Auto-scroll to latest message; pause on manual scroll-up
- No horizontal overflow at 375px width

## Security guardrails

- PII mask before every LLM call — including retrieved chunks and conversation history
- No raw query/response logging at INFO level
- All versions pinned in both `requirements.txt` and `package.json` (no `^` or `~`)
- Non-root in both Dockerfiles
- No secrets in code — `.env.example` with placeholders
- Pydantic validation on all endpoints; input length enforced
- `react-markdown` default settings; no `rehypeRaw`
- CSP headers on nginx: `default-src 'self'` minimum
- Conversation IDs generated via `crypto.randomUUID()`, never in URLs

## Definition of done for any task

1. `docker compose up` succeeds end-to-end
2. `/chat` handles multi-turn correctly across ≥ 2 documents
3. Telemetry row written for every interaction
4. Drift job produces a structured report; distinguish completed/insufficient, alert, and execution-error exit codes: `python -m monitoring.drift_job.run_drift --trigger adhoc`
5. New code has at least one test
6. `code-reviewer` and `security-scanner` agents have reviewed
7. `ruff check .` and `pytest` pass
8. `npm run lint` and `npm run build` pass
9. Mobile emulation passes at 375px

## Roadmap (post-MVP, architecture must support these without rewrites)

- Cross-encoder reranker (`bge-reranker-v2-m3` via Ollama)
- Hybrid search (BM25 + vector)
- Context recall metric (requires golden answer set)
- Agentic tools: `search_regulations`, `summarise_section`, `compare_clauses`
- A/B testing harness: two prompt variants in parallel, compared via feedback
- RAGAS-based eval in CI (runs on PRs that touch RAG components)
- User auth via JWT
- Postgres migration path (SQLAlchemy schema is already Postgres-compatible)
