from __future__ import annotations

from unittest.mock import Mock

import chromadb
import pytest

from app.rag import ingest
from app.rag.chunking import ExtractedDoc, chunk_doc


def chunks(sections):
    return chunk_doc(ExtractedDoc(title="Sample", sections=[(title, [title], text) for title, text in sections]), "sample")


def test_real_chroma_repeat_and_modified_document(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collection = client.get_or_create_collection("ingestion_test")
    first = chunks([("A", "alpha"), ("B", "beta")])
    assert ingest._upsert_chunks(collection, first, [[1., 0.], [0., 1.]]) == (2, 0)
    assert ingest._upsert_chunks(collection, first, [[1., 0.], [0., 1.]]) == (0, 2)
    changed = chunks([("New", "new"), ("A", "alpha")])
    assert ingest._upsert_chunks(collection, changed, [[1., 1.], [1., 0.]]) == (1, 1)
    stored = collection.get()
    assert set(stored["ids"]) == {chunk.chroma_id for chunk in changed}
    index = stored["ids"].index(first[0].chroma_id)
    assert stored["metadatas"][index]["chunk_index"] == 1
    assert collection.count() == 2


def test_ingestion_failure_propagates(tmp_path, monkeypatch):
    (tmp_path / "sample.pdf").touch()
    monkeypatch.setattr(ingest.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(ingest, "_chroma_client", Mock())
    monkeypatch.setattr(ingest, "_get_collection", Mock())
    monkeypatch.setattr(ingest, "ingest_pdf", Mock(side_effect=ConnectionError("model offline")))
    with pytest.raises(RuntimeError, match="model offline"):
        ingest.main()


def test_failed_replacement_does_not_delete_previous_chunks():
    collection = Mock()
    collection.get.return_value = {"ids": ["old-chunk"]}
    collection.upsert.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        ingest._upsert_chunks(collection, chunks([("New", "new")]), [[1., 0.]])
    collection.delete.assert_not_called()


def test_container_ingestion_uses_release_revision(monkeypatch):
    monkeypatch.setattr(ingest.settings, "commit_sha", "a" * 40)
    assert ingest._get_pipeline_version() == "a" * 12
