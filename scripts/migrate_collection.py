"""Rename a quiescent Chroma collection without recomputing its embeddings.

Stop every writer first. The explicit external record contains a full pre-migration
snapshot, so it is private data and must be kept with the operator's backups.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGET = "aegis_rag_documents"


def external_record(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Migration record must be outside the project directory")
    return path


def save_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(record, output, ensure_ascii=False, sort_keys=True, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot(collection: Any, batch_size: int = 500) -> dict:
    """Read stored vectors directly; no embedding function is invoked."""
    count = collection.count()
    rows = []
    for offset in range(0, count, batch_size):
        page = collection.get(
            offset=offset, limit=batch_size, include=["documents", "metadatas", "embeddings"]
        )
        for index, identifier in enumerate(page["ids"]):
            vector = page["embeddings"][index]
            if hasattr(vector, "tolist"):
                vector = vector.tolist()
            rows.append({
                "id": identifier,
                "document": page["documents"][index] if page["documents"] is not None else None,
                "metadata": page["metadatas"][index] if page["metadatas"] is not None else None,
                "embedding": vector,
            })
    rows.sort(key=lambda row: row["id"])
    if collection.count() != count or len(rows) != count or len({r["id"] for r in rows}) != count:
        raise RuntimeError("Collection changed during snapshot; stop all writers and retry")
    payload = {
        "collection_id": str(collection.id),
        "metadata": collection.metadata,
        "count": count,
        "records": rows,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return {**payload, "sha256": hashlib.sha256(encoded).hexdigest()}


def find_collection(client: Any, name: str) -> Any | None:
    # Only an actual not-found error means absence; connectivity errors must propagate.
    from chromadb.errors import NotFoundError

    try:
        return client.get_collection(name, embedding_function=None)
    except NotFoundError:
        return None


def migrate(client: Any, source_name: str, target_name: str, record_path: Path,
            *, dry_run: bool = False) -> dict:
    record_path = external_record(record_path)
    if source_name == target_name:
        raise ValueError("Source and target names must differ")
    record = json.loads(record_path.read_text()) if record_path.exists() else None
    if record is not None:
        if (record.get("source_name"), record.get("target_name")) != (source_name, target_name):
            raise ValueError("Record belongs to a different migration")
        if record.get("schema_version") != 1 or "snapshot" not in record:
            raise ValueError("Unsupported or incomplete migration record")
    source = find_collection(client, source_name)
    target = find_collection(client, target_name)
    if source is not None and target is not None:
        raise RuntimeError("Target collection already exists; nothing was overwritten")
    if source is None:
        if target is None or record is None:
            raise RuntimeError("Source missing; cannot verify migration without its saved record")
        if snapshot(target) != record["snapshot"]:
            raise RuntimeError("Target does not match the saved snapshot; refusing to accept migration")
        if not dry_run:
            record["status"] = "completed"
            record.pop("error", None)
            save_record(record_path, record)
        return {"status": "already_migrated", "count": record["snapshot"]["count"]}

    before = snapshot(source)
    if record is not None and before != record["snapshot"]:
        raise RuntimeError("Source does not match the saved snapshot; use a new backup and record")
    if dry_run:
        return {"status": "dry_run", "count": before["count"], "sha256": before["sha256"]}
    record = {
        "schema_version": 1, "source_name": source_name, "target_name": target_name,
        "snapshot": before, "status": "prepared",
    }
    # Durable evidence must exist before changing the database.
    save_record(record_path, record)
    try:
        source.modify(name=target_name)
        target = find_collection(client, target_name)
        if target is None or snapshot(target) != before:
            raise RuntimeError("Post-migration content verification failed")
        record["status"] = "completed"
        save_record(record_path, record)
    except Exception as error:
        try:
            target = find_collection(client, target_name)
            original = find_collection(client, source_name)
            if target is not None:
                if str(target.id) != before["collection_id"] or original is not None:
                    raise RuntimeError("Collection identity conflict; manual recovery required")
                target.modify(name=source_name)
            restored = find_collection(client, source_name)
            if restored is None or snapshot(restored) != before:
                raise RuntimeError("Restored collection differs from backup; manual recovery required")
            record["status"] = "rolled_back"
        except Exception as recovery_error:
            record["status"] = "recovery_required"
            record["recovery_error"] = str(recovery_error)
        record["error"] = str(error)
        try:
            save_record(record_path, record)
        except Exception as record_error:
            raise RuntimeError(
                f"Migration failed; {record['status']}; record update failed: {record_error}"
            ) from error
        raise RuntimeError(f"Migration failed; {record['status']}: {error}") from error
    return {"status": "completed", "count": before["count"], "sha256": before["sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    connection = parser.add_mutually_exclusive_group(required=True)
    connection.add_argument("--path", type=Path, help="Existing local Chroma directory")
    connection.add_argument("--host", help="Chroma HTTP host")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ssl", action="store_true")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--target-name", default=TARGET)
    parser.add_argument("--record", required=True, type=Path, help="Private record outside project")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        external_record(args.record)
        import chromadb

        if args.path:
            if not (args.path / "chroma.sqlite3").is_file():
                raise ValueError("Local path must contain an existing Chroma database")
            client = chromadb.PersistentClient(path=str(args.path.resolve()))
        else:
            client = chromadb.HttpClient(host=args.host, port=args.port, ssl=args.ssl)
        result = migrate(client, args.source_name, args.target_name, args.record,
                         dry_run=args.dry_run)
        print(json.dumps(result))
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "message": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
