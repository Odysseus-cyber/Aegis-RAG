# Aegis-RAG development and delivery

## Local changes

Clone [Odysseus-cyber/Aegis-RAG](https://github.com/Odysseus-cyber/Aegis-RAG), run `make setup`, then `make doctor`. Python 3.11 and Node 24 are required. Use `make backend` and `make frontend` in separate terminals for the native development application.

Before submitting a change:

```bash
make lint
make test-local
cd frontend
npm ci
npm test
npm run lint
npm run build
```

Keep `.env`, PDFs, model files, databases, local indexes, backups and `.runtime` out of Git. Dedicated synthetic test fixtures belong in `tests/`. Existing `ccrag_*` storage and metric names and the `compliance_docs` collection remain compatible.

## Unified CI

[Delivery](https://github.com/Odysseus-cyber/Aegis-RAG/actions/workflows/delivery.yml) runs on pull requests, pushes to `main`, and manual dispatch. It validates pinned dependency installation, Python lint/tests, frontend tests/lint/build and the 200KB gzip JavaScript budget, workflow/Compose/monitoring configuration, and backend/frontend/drift Docker builds.

Tests use temporary databases and deterministic model substitutes. Hosted CI does not read local PDFs or require a running Mac Ollama. Failed jobs retain test reports and logs. Caches, job timeouts, cancellation of superseded work, and minimum permissions keep runs bounded.

## Release and deploy

Only successful `main` runs publish the three images to `ghcr.io/odysseus-cyber/aegis-rag/{backend,frontend,drift}`. Each image supports `linux/amd64` and `linux/arm64`, has a full commit SHA tag, and embeds source/build metadata. Only after all images are published is the release `sha-<SHA>` created with `delivery.json` and `deployment.tar.gz`.

The delivery manifest binds the source SHA, Actions run, deployment files, and all image digests into one release. Deployment reads that manifest rather than independently choosing image tags.

```bash
make deploy-demo VERSION=<full-commit-SHA>
make verify-demo
make evaluate-demo
make rollback-demo
```

Deployment pulls all images first, checks model availability and container-to-host connectivity, starts the isolated stack, then verifies ingestion, two real chat turns, citations and feedback. Functional failure returns a nonzero status and restores the previous application release when one exists. On the first deployment there is no previous release; failure is reported explicitly. Persistent data is retained.

The post-deployment quality evaluation is informational: insufficient samples and model quality alerts remain visible and do not trigger rollback. Real evaluation and isolated demonstration scenarios must be labeled separately. See [deployment](deployment.md), [monitoring](monitoring.md), and the main [README](../README.md) for commands and actual acceptance evidence.
