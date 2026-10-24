---
description: Ingest all PDFs in data/ into ChromaDB and generate llms-txt artifacts
---

Ingest documents into Aegis-RAG. Run after adding new PDFs to `data/`.

## Steps

1. **Select the target environment** — confirm configured data, index and telemetry paths. Keep the existing frozen evaluation baseline; refresh it only when deliberately establishing a new reference with sufficient history. Ingestion itself does not require or automatically imply a quality report.

2. **Discover documents** — list all `*.pdf` files in `data/`. For each:

3. **Extract text** — use PyMuPDF (`fitz`). Preserve section headings by detecting font size changes and bold formatting. Skip headers/footers (ignore content in top/bottom 5% of page height).

4. **Generate llms-txt artifact** — write `llms-txt/<doc_stem>.md`:
   ```
   ---
   title: <extracted or filename>
   source: <original URL if known, else 'local'>
   ingested_at: <ISO timestamp>
   pipeline_version: <git SHA>
   ---

   ## <Section heading>

   <section content, tables as markdown tables>
   ```
   This file is a standalone deliverable — clean enough to be fed directly to any LLM.

5. **Chunk by section** — split at `##` and `###` boundaries. Each chunk carries metadata:
   `{doc_name, doc_title, section, section_path, chunk_index, ingested_at, content_hash, pipeline_version}`

6. **Embed and upsert** — embed each chunk via `nomic-embed-text`. Upsert into ChromaDB using `(doc_name, chunk_index, content_hash)` as the composite key — idempotent.

7. **Report** — print:
   ```
   Ingested: <doc_name>
   Chunks: <N>
   Skipped (unchanged): <M>
   Time: <seconds>
   ```

8. **Optional post-ingestion report** — after collecting real questions and answers, run `make evaluate-demo` for the demo deployment, or:
   ```bash
   python -m monitoring.drift_job.run_drift --trigger adhoc --window-hours 24
   ```
   Report actual sample counts, alerts and skips. The job uses a frozen nonoverlapping reference; it cannot assess a new empty knowledge base from ingestion alone.

Stop and ask if:
- A PDF fails to extract meaningful text (likely scanned image — OCR not in scope for MVP)
- Chunk count for a doc changes by more than 20% from a previous ingest
