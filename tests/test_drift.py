import json
import struct
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import create_engine

from app.telemetry.schema import Base
from monitoring.drift_job import feedback_analysis, output_drift, quality_eval
from monitoring.drift_job.common import Config, connect, load_window, windows
from monitoring.drift_job.demo import build_report, fixture
from monitoring.drift_job.run_drift import main, metrics_text, publish, run
from monitoring.drift_job.snapshot import capture, get_baseline

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


@pytest.fixture
def drift_db(tmp_path):
    path = tmp_path / "telemetry.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    config = Config(db_path=str(path), baseline_path=str(tmp_path / "baseline.json"))
    with connect(path) as con:
        con.execute("INSERT INTO conversations (id,created_at,updated_at) VALUES ('c',?,?)",
                    (NOW.isoformat(), NOW.isoformat()))
        con.commit()
    return config


def add_message(con, mid="m", when=NOW-timedelta(hours=1), embedding=True, text=True):
    chunks = [{"chunk_id": "chunk-1", "score": .9}]
    if text:
        chunks[0]["text"] = "Employees must report incidents within 24 hours."
    con.execute("INSERT INTO messages (id,conversation_id,role,content,rewritten_query,"
                "retrieved_chunks,response_length,response_embedding,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (mid, "c", "assistant", "Report in 24 hours.", "When to report?", json.dumps(chunks),
                 19, struct.pack("2f", 1, 0) if embedding else None, when.isoformat()))
    con.commit()


def test_windows_and_snapshot_are_disjoint_and_frozen(drift_db):
    start, split, end = windows(NOW)
    assert (split-start).days == 7
    assert (end-split).days == 1
    with connect(drift_db.db_path) as con:
        add_message(con, "reference", split-timedelta(seconds=1))
        add_message(con, "boundary", split)
        add_message(con, "end", end)
        snapshot = capture(con, drift_db, "sha", NOW)
        assert [m["id"] for m in snapshot["samples"]["messages"]] == ["reference"]
        assert [m["id"] for m in load_window(con, split, end)["messages"]] == ["boundary"]
        con.execute("UPDATE messages SET response_length=999")
        con.commit()
        assert get_baseline(con, drift_db, "new-sha", NOW, 24) == snapshot
        with pytest.raises(ValueError, match="overlaps"):
            get_baseline(con, drift_db, "sha", NOW-timedelta(hours=1), 24)


@pytest.mark.parametrize("scenario,code", [("passed", 0), ("alert", 1), ("insufficient_data", 0), ("error", 2)])
def test_synthetic_scenarios(scenario, code):
    report = build_report(scenario)
    assert report["status"] == scenario
    assert report["exit_code"] == code
    assert report["source"] == "synthetic_demo"


def test_drift_is_deterministic_and_zero_baseline_alerts():
    assert output_drift.evaluate(fixture(), fixture(True)) == output_drift.evaluate(fixture(), fixture(True))
    assert feedback_analysis.evaluate(fixture(), fixture(True))[0]["threshold"] == .2
    assert feedback_analysis.evaluate(fixture(), fixture())[0]["status"] == "passed"
    assert feedback_analysis.evaluate(fixture(count=9), fixture(True))[0]["status"] == "insufficient_data"


def test_backfill_only_missing_masked_answers(drift_db):
    client = Mock()
    client.embed.return_value = {"embeddings": [[.5, .75]]}
    with connect(drift_db.db_path) as con:
        add_message(con, embedding=False)
        start, _, end = windows(NOW)
        assert quality_eval.backfill(con, drift_db, start, end, client) == 1
        assert quality_eval.backfill(con, drift_db, start, end, client) == 0
        assert client.embed.call_args.kwargs["input"] == "Report in 24 hours."
        assert con.execute("SELECT response_embedding FROM messages").fetchone()[0] == struct.pack("2f", .5, .75)


def test_quality_uses_original_text_persists_and_skips_reference_metric(drift_db):
    client = Mock()
    client.chat.return_value = {"message": {"content": json.dumps({
        "faithfulness": {"score": .9, "reason": "supported"},
        "answer_relevance": {"score": .8, "reason": "answers question"}})}}
    with connect(drift_db.db_path) as con:
        add_message(con)
        _, start, end = windows(NOW)
        evaluated = quality_eval.evaluate(con, drift_db, load_window(con, start, end), "run", client)
        prompt = client.chat.call_args.kwargs["messages"][0]["content"]
        assert "Employees must report incidents" in prompt
        assert "chunk-1" not in prompt
        assert evaluated[2]["status"] == "insufficient_data"
        assert con.execute("SELECT count(*) FROM eval_results").fetchone()[0] == 2


def test_invalid_judge_output_is_error(drift_db, monkeypatch):
    with connect(drift_db.db_path) as con:
        add_message(con)
    client = Mock()
    client.chat.return_value = {"message": {"content": "not json"}}
    monkeypatch.setattr(quality_eval.ollama, "Client", lambda **kw: client)
    report = run(drift_db, now=NOW)
    assert report["exit_code"] == 2
    assert any(m["metric"] == "quality_eval" and m["status"] == "error" for m in report["metrics"])


def test_unresolved_old_context_is_skipped(drift_db):
    with connect(drift_db.db_path) as con:
        add_message(con, text=False)
        _, start, end = windows(NOW)
        client = Mock()
        metrics = quality_eval.evaluate(con, drift_db, load_window(con, start, end), "run",
                                        client, resolver=lambda _: [])
        assert all(m["status"] == "insufficient_data" for m in metrics)
        client.chat.assert_not_called()


def test_missing_db_and_write_failure_are_errors(drift_db, monkeypatch):
    config = Config(db_path=drift_db.db_path + "-absent", baseline_path=drift_db.baseline_path)
    assert run(config, now=NOW)["exit_code"] == 2
    import monitoring.drift_job.run_drift as runner
    monkeypatch.setattr(runner, "persist", Mock(side_effect=OSError("readonly")))
    assert run(drift_db, now=NOW)["exit_code"] == 2


def test_push_replaces_group_and_omits_stale_scores(monkeypatch):
    report = build_report("error")
    text = metrics_text(report)
    assert 'aegis_rag_drift_status{metric_name="execution"} 3' in text
    assert not any(line.startswith("aegis_rag_drift_value{") for line in text.splitlines())
    import monitoring.drift_job.run_drift as runner
    urlopen = MagicMock()
    monkeypatch.setattr(runner, "urlopen", urlopen)
    publish(Config(pushgateway="http://pushgateway:9091"), report, "synthetic_demo")
    request = urlopen.call_args.args[0]
    assert request.method == "PUT"
    assert request.full_url.endswith("/source/synthetic_demo")


def test_main_writes_structured_error_report(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(tmp_path / "missing.db"))
    report = tmp_path / "report.json"
    assert main(["--trigger", "ci", "--report", str(report)]) == 2
    assert json.loads(report.read_text())["status"] == "error"


def test_reference_answers_enable_context_precision_and_sample_cap(drift_db, tmp_path):
    reference_path = tmp_path / "references.json"
    reference_path.write_text(json.dumps({f"m{i}": "Report within 24 hours" for i in range(12)}))
    drift_db.reference_dataset = str(reference_path)
    client = Mock()
    client.chat.return_value = {"message": {"content": json.dumps({
        name: {"score": .8, "reason": "supported"} for name in quality_eval.THRESHOLDS
    })}}
    with connect(drift_db.db_path) as con:
        for i in range(12):
            add_message(con, f"m{i}")
        _, start, end = windows(NOW)
        metrics = quality_eval.evaluate(con, drift_db, load_window(con, start, end), "run", client)
        assert client.chat.call_count == 10
        assert metrics[2]["status"] == "passed"
        assert metrics[2]["current_n"] == 10
        assert con.execute("SELECT count(*) FROM eval_results").fetchone()[0] == 30


def test_embedding_failure_does_not_freeze_broken_baseline(drift_db, monkeypatch):
    from pathlib import Path
    with connect(drift_db.db_path) as con:
        add_message(con, embedding=False)
    client = Mock()
    client.embed.side_effect = ConnectionError("Ollama offline")
    monkeypatch.setattr(quality_eval.ollama, "Client", lambda **kw: client)
    report = run(drift_db, now=NOW)
    assert report["exit_code"] == 2
    assert not Path(drift_db.baseline_path).exists()


def test_publish_failure_is_execution_error(drift_db, monkeypatch):
    import monitoring.drift_job.run_drift as runner
    monkeypatch.setattr(runner, "publish", Mock(side_effect=ConnectionError("unreachable")))
    report = run(drift_db, now=NOW)
    assert report["exit_code"] == 2
    assert report["metrics"][-1]["metric"] == "pushgateway"


def test_psi_detects_shift_for_low_cardinality_reference():
    reference = [100] * 19 + [200]
    assert output_drift._psi(reference, [1000] * 20) > .2
    assert output_drift._psi(reference, reference) == 0


def test_dashboard_status_queries_are_instant():
    from pathlib import Path
    dashboard = json.loads(Path("monitoring/grafana/dashboards/model-quality.json").read_text())
    for panel in dashboard["panels"]:
        if panel["type"] == "stat":
            assert all(t["instant"] and not t["range"] for t in panel["targets"])
