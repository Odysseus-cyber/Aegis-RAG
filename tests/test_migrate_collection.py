"""Collection migrations use isolated Chroma stores and explicit private records."""
import json
from pathlib import Path

import chromadb
import pytest
from chromadb.config import Settings

from scripts import migrate_collection as migration


@pytest.fixture
def store(tmp_path):
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma"), settings=Settings(anonymized_telemetry=False)
    )
    source = client.create_collection("source_documents", metadata={"hnsw:space": "cosine"})
    return client, source, tmp_path / "archive" / "migration.json"


def add_rows(source):
    source.add(ids=["chunk-b", "chunk-a"], embeddings=[[0.1, 0.2], [0.3, 0.4]],
               documents=["second paragraph", "first paragraph"],
               metadatas=[{"doc_name": "test", "page": 2}, {"doc_name": "test", "page": 1}])


def run(store, **kwargs):
    client, _, record = store
    return migration.migrate(client, "source_documents", migration.TARGET, record, **kwargs)


def test_preserves_all_records_vectors_metadata_and_identity(store):
    client, source, record = store
    add_rows(source)
    expected = migration.snapshot(source, batch_size=1)
    assert run(store)["status"] == "completed"
    assert migration.find_collection(client, "source_documents") is None
    assert migration.snapshot(client.get_collection(migration.TARGET)) == expected
    saved = json.loads(record.read_text())
    assert saved["snapshot"] == expected
    assert saved["status"] == "completed"
    assert record.stat().st_mode & 0o777 == 0o600


def test_empty_collection_migrates(store):
    assert run(store)["count"] == 0
    assert store[0].get_collection(migration.TARGET).count() == 0


def test_repeat_verifies_saved_evidence_without_changing_data(store):
    add_rows(store[1])
    run(store)
    assert run(store) == {"status": "already_migrated", "count": 2}


def test_resume_after_process_stops_between_rename_and_completion_record(store):
    client, source, record = store
    add_rows(source)
    migration.save_record(record, {
        "schema_version": 1, "source_name": "source_documents", "target_name": migration.TARGET,
        "snapshot": migration.snapshot(source), "status": "prepared",
    })
    source.modify(name=migration.TARGET)
    assert run(store)["status"] == "already_migrated"
    assert json.loads(record.read_text())["status"] == "completed"
    assert client.get_collection(migration.TARGET).count() == 2


def test_target_conflict_never_overwrites_either_collection(store):
    client, source, record = store
    add_rows(source)
    client.create_collection(migration.TARGET)
    with pytest.raises(RuntimeError, match="Target collection already exists"):
        run(store)
    assert client.get_collection("source_documents").count() == 2
    assert client.get_collection(migration.TARGET).count() == 0
    assert not record.exists()


def test_dry_run_does_not_rename_or_write_record(store):
    assert run(store, dry_run=True)["status"] == "dry_run"
    assert migration.find_collection(store[0], migration.TARGET) is None
    assert not store[2].exists()


def test_verification_failure_restores_name_and_data(store, monkeypatch):
    add_rows(store[1])
    actual = migration.snapshot
    calls = 0

    def transient_read_failure(collection):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Simulated connection interruption")
        return actual(collection)

    monkeypatch.setattr(migration, "snapshot", transient_read_failure)
    with pytest.raises(RuntimeError, match="rolled_back"):
        run(store)
    assert store[0].get_collection("source_documents").count() == 2
    assert migration.find_collection(store[0], migration.TARGET) is None
    assert json.loads(store[2].read_text())["status"] == "rolled_back"
    monkeypatch.setattr(migration, "snapshot", actual)
    assert run(store)["status"] == "completed"


def test_failed_backup_never_changes_collection(store, monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(migration, "save_record", fail)
    with pytest.raises(OSError, match="disk full"):
        run(store)
    assert migration.find_collection(store[0], "source_documents") is not None
    assert migration.find_collection(store[0], migration.TARGET) is None


def test_repeat_rejects_modified_target(store):
    run(store)
    add_rows(store[0].get_collection(migration.TARGET))
    with pytest.raises(RuntimeError, match="does not match"):
        run(store)


def test_missing_source_without_record_cannot_claim_success(store):
    store[1].modify(name=migration.TARGET)
    with pytest.raises(RuntimeError, match="cannot verify"):
        run(store)


def test_internal_record_and_same_names_rejected(store):
    with pytest.raises(ValueError, match="outside"):
        migration.migrate(store[0], "source_documents", migration.TARGET,
                          migration.ROOT / "record.json")
    with pytest.raises(ValueError, match="must differ"):
        migration.migrate(store[0], "source_documents", "source_documents", store[2])


def test_wrong_record_identity_rejected(store):
    record = store[2]
    migration.save_record(record, {"source_name": "other", "target_name": migration.TARGET})
    with pytest.raises(ValueError, match="different migration"):
        run(store)


def test_connection_error_is_not_misreported_as_missing():
    class OfflineClient:
        def get_collection(self, *args, **kwargs):
            raise ConnectionError("offline")

    with pytest.raises(ConnectionError, match="offline"):
        migration.find_collection(OfflineClient(), "source_documents")


def test_record_symlink_inside_project_rejected(tmp_path):
    pointer = tmp_path / "pointer"
    pointer.symlink_to(migration.ROOT, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        migration.external_record(pointer / "record.json")
    assert isinstance(migration.external_record(tmp_path / "private.json"), Path)


def test_recovery_failure_is_explicit_and_preserves_backup(store, monkeypatch):
    add_rows(store[1])
    before = migration.snapshot(store[1])
    actual = migration.snapshot
    calls = 0

    def unavailable_after_rename(collection):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ConnectionError("store unavailable")
        return actual(collection)

    monkeypatch.setattr(migration, "snapshot", unavailable_after_rename)
    with pytest.raises(RuntimeError, match="recovery_required"):
        run(store)
    saved = json.loads(store[2].read_text())
    assert saved["snapshot"] == before
    assert saved["status"] == "recovery_required"
    assert "store unavailable" in saved["recovery_error"]


def test_source_change_after_rolled_back_attempt_requires_new_snapshot(store):
    client, source, record = store
    migration.save_record(record, {
        "schema_version": 1, "source_name": "source_documents", "target_name": migration.TARGET,
        "snapshot": migration.snapshot(source), "status": "rolled_back",
    })
    add_rows(source)
    with pytest.raises(RuntimeError, match="Source does not match"):
        run(store)
    assert client.get_collection("source_documents").count() == 2
    assert migration.find_collection(client, migration.TARGET) is None
