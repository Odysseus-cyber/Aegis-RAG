---
description: Run explicit drift and local Ollama rubric reporting against a configured deployment
---

Run Aegis-RAG quality reporting against the intended database, Ollama, ChromaDB and Pushgateway configuration. Native development does not install a scheduler. The Kubernetes CronJob is an optional example.

## Usage

```bash
# Published local demo
make evaluate-demo

# Configured native reporting environment
python -m monitoring.drift_job.run_drift --trigger adhoc --window-hours 24 --report .runtime/reports/drift.json

# Deliberately refresh the frozen reference after sufficient history exists
python -m monitoring.drift_job.snapshot --pipeline-version <deployed-sha>
```

The `--trigger` value (`cron`, `ci`, or `adhoc`) labels a report; it does not schedule execution or make quality a CI gate. There is no `--force-eval` option.

## What the job does

1. Backfill missing embeddings for saved, masked assistant answers.
2. Capture a seven-day reference preceding the current 24-hour window on the first run, then retain its samples and boundaries. Recapture explicitly rather than overwriting it on every invocation.
3. Compare retrieval scores with SciPy KS, answer embeddings with seeded NumPy cosine sampling, answer lengths with PSI, and feedback rates. Each statistical comparison requires at least 10 valid samples per window.
4. Score up to 10 current answers with the configured local Ollama JSON rubric and actual retrieved passages. Scores are model estimates, not DeepEval metrics. Context precision requires reference answers.
5. Save actual scores to existing tables and a structured JSON report. PUT the complete metric group to Pushgateway, including values, counts, statuses and timestamps; remove obsolete values rather than emitting false zero scores.
6. Return `0` for completed reports including insufficient data, `1` for measured alerts, and `2` for execution errors. Quality alerts do not gate deployment or trigger rollback.

Use `.runtime` or a configured private report path for snapshots and reports containing message data. Demonstration scenarios use `python -m monitoring.drift_job.demo` and the separate `synthetic_demo` metric group; never present these as real model evidence.

See `docs/monitoring.md` for exact thresholds and the `drift-analyst` agent for interpretation.
