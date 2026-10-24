# Aegis-RAG deployment

## Native development

Use `make setup`, `make doctor`, `make backend`, and `make frontend` as described in the main [README](../README.md). The native application uses backend `127.0.0.1:8000`, frontend `127.0.0.1:5173`, and the existing local Ollama.

## Published local demo

The unified [delivery workflow](../.github/workflows/delivery.yml) publishes backend, frontend, and drift images for AMD64 and ARM64 under `ghcr.io/odysseus-cyber/aegis-rag`. Each successful release uses the tag `sha-<full-commit-SHA>` and includes `delivery.json` plus `deployment.tar.gz`. The manifest records exact image digests so a deployment uses one complete revision.

```bash
make deploy-demo VERSION=<full-commit-SHA>
make verify-demo
make evaluate-demo
make rollback-demo
```

Docker Desktop and host Ollama must be running, with `gemma3:1b` and `nomic-embed-text` installed. Containers reach Ollama at `host.docker.internal:11434`; the deployment preflight tests that connection and checks installed models.

The demo generates a random Grafana administrator password in the private local
file `.runtime/aegis-demo/grafana-admin-password` and reuses it across releases.
Log in as `admin` using that file's value. Keep the password and generated Compose
configuration private; both are stored with owner-only permissions. An existing
Grafana database retains its initialized password, so preserve the password file
alongside its data when archiving or restoring an installation.

| Service | Loopback URL |
|---|---|
| Frontend | http://127.0.0.1:15173 |
| Backend | http://127.0.0.1:18000 |
| ChromaDB | http://127.0.0.1:18001 |
| Prometheus | http://127.0.0.1:19090 |
| Pushgateway | http://127.0.0.1:19091 |
| Grafana | http://127.0.0.1:13000 |

Demo data, current and previous manifests, and run evidence live under `.runtime/aegis-demo`. The deployment uses dedicated sample PDFs and persistent directories, and preserves the native app's PDFs, index and chat history. The UI footer displays the backend revision and links to its Actions run; `GET /version` returns the application name, full commit SHA, build time and Actions URL.

Deployment pulls the complete image set before replacing services, then checks health and performs two real chat turns, repeat ingestion and immediate feedback. A functional failure is reported and restores the previous application release when available. First deployment failure remains a failed deployment. Rollback never clears persistent data and does not roll back database contents.

The authoritative deployment record is `.runtime/aegis-demo/state.json`, which stores
the current and previous verified releases together with storage namespace
`aegis-rag-v2`. Deployment and rollback commit this pair with one atomic file
replacement after verification. If that commit fails, the prior application is
restored and the original state file is retained; a first deployment is stopped
without removing persistent data. Old separate `current.json` or `previous.json`
files without `state.json` are rejected before service changes. Archive those
records with the pre-migration application and data; do not convert them into a
rollback target. The first verified release in the new namespace has no ordinary
rollback target until another compatible release passes acceptance.

Quality evaluation runs after functional acceptance and reports independently. Alerts and insufficient samples do not block deployment or trigger rollback; execution failures remain explicit. See [monitoring](monitoring.md) for the metric and exit-code contracts.

## Development Compose

The root `docker-compose.yml` builds directly from source and runs its own Ollama. Its default ports overlap the native app, so stop conflicting services or use the isolated validation helper described in the main README. The published demo above is the preferred side-by-side demonstration.

```bash
cp .env.example .env  # only if .env does not already exist
# Set a private random GRAFANA_ADMIN_PASSWORD in .env; the example is only a placeholder.
# Edit the remaining settings as needed, then:
docker compose up -d --build
docker compose exec backend python -m app.rag.ingest
```

The backend waits for model initialization, and frontend startup waits for backend health. Nginx keeps response buffering disabled for streamed answers. Writable telemetry and Chroma paths must match their mounts; do not mount the telemetry database read-only because evaluation writes results and missing embeddings.

## Kubernetes examples

`k8s/manifests.yaml` and `k8s/cronjob-drift.yaml` use namespace `aegis-rag` and the same GHCR image names. Replace every `REPLACE_WITH_COMMIT_SHA` with a tested release SHA before applying. These are examples; Kubernetes deployment is outside the local acceptance target.

The manifests contain Ollama, ChromaDB, backend and frontend services plus their configuration and volumes. Monitoring endpoints referenced by the configuration must be provisioned separately. The nightly drift CronJob uses shared configuration and a writable telemetry PVC. Choose storage that supports the cluster's scheduling and single-writer SQLite requirements.

The current storage namespace uses `aegis_rag_conversations`, `aegis_rag_active_conversation`, and the `aegis_rag_documents` collection. Metrics use `aegis_rag_*`; database tables and message IDs remain unchanged. Existing installations must migrate browser data and collections before switching versions. Normal rollback is limited to versions using this namespace; restoring an earlier namespace requires its paired application and data archive. Do not change an existing cluster namespace without migrating its persistent volumes.

## One-time browser storage migration

Before upgrading an existing installation, close its other browser tabs and open
`/storage-migration.html` on each previously used origin (including the native and
container ports, and each hostname). Enter the two source keys from the private
migration inventory. The application itself does not read any prior namespace.

The utility exports a JSON snapshot of both source and destination keys. Save it
in the private migration archive, then select that exact file on the page to
verify the saved backup before enabling migration. The page displays only counts
and status, not chat contents. A destination conflict or a concurrent change stops
the operation without overwriting either copy. After writing and reading back
both destinations, the utility removes the corresponding source keys. Repeating
a completed migration is harmless; an interrupted operation can be retried after
checking storage access. The downloaded backup contains private conversations
and must never be committed or uploaded with project materials.

### Save browser snapshots directly to a private local archive

If the browser cannot reliably save or select a downloaded backup, stop the
application occupying the origin's port and run the temporary helper from the
project directory:

```bash
.venv/bin/python scripts/serve_storage_migration.py \
  --port 15173 --archive-dir "$ARCHIVE/browser/15173"
```

Set `ARCHIVE` to the absolute private migration archive path outside the project
before running this command. For the native application's storage, use port
`5173` and a separate archive subdirectory. The helper binds only `127.0.0.1`;
open `/storage-migration.html` using the same hostname and port as the application
whose browser data is being migrated. `localhost` and `127.0.0.1` are separate
browser origins and must be processed separately when both were used.

After inspecting the snapshot, choose **保存到本机私有归档并验证**. The helper
writes a new private JSON file, reads back its exact bytes, and returns a receipt.
The page checks the receipt's digest, byte count, and origin before enabling
migration. The usual download-and-upload verification remains available. A normal
published application does not implement `/migration-backup`; an unavailable
helper never authorizes skipping the backup. Stop the temporary helper with
Ctrl-C after finishing each origin, before restarting the application.

The migration HTML and module imports carry an explicit asset version so a
previous browser cache cannot silently load an older migration interface.
