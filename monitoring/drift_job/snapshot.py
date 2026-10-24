"""Freeze baseline samples and window boundaries; refresh only explicitly."""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

from monitoring.drift_job.common import Config, connect, load_window, utcnow, windows, write_json
from monitoring.drift_job.quality_eval import backfill
from monitoring.drift_job.retrieval_drift import scores


def capture(con, config, version, now, window_hours=24, reference_hours=168):
    start, end, _ = windows(now, window_hours, reference_hours)
    data = load_window(con, start, end)
    snapshot = {"id": str(uuid.uuid4()), "pipeline_version": version,
                "captured_at": now.isoformat(), "window_start": start.isoformat(),
                "window_end": end.isoformat(), "samples": data}
    retrieval = scores(data)
    lengths = [m["response_length"] for m in data["messages"] if m["response_length"] is not None]
    feedback = data["feedback"]
    con.execute(
        "INSERT INTO baseline_snapshots (id,pipeline_version,captured_at,retrieval_score_p50,"
        "retrieval_score_p95,response_length_p50,feedback_thumbsdown_ratio,sample_size) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (snapshot["id"], version or "unknown", now.isoformat(),
         float(np.percentile(retrieval, 50)) if retrieval else None,
         float(np.percentile(retrieval, 95)) if retrieval else None,
         float(np.percentile(lengths, 50)) if lengths else None,
         sum(f["rating"] == -1 for f in feedback)/len(feedback) if feedback else None,
         len(data["messages"])),
    )
    con.commit()
    write_json(config.baseline_path, snapshot)
    return snapshot


def get_baseline(con, config, version, now, window_hours):
    if not Path(config.baseline_path).exists():
        return capture(con, config, version, now, window_hours)
    snapshot = json.loads(Path(config.baseline_path).read_text())
    _, current_start, _ = windows(now, window_hours)
    if datetime.fromisoformat(snapshot["window_end"]) > current_start:
        raise ValueError("Frozen baseline overlaps current window; explicitly recapture baseline")
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description="Freeze Aegis-RAG baseline samples")
    parser.add_argument("--pipeline-version", required=True)
    parser.add_argument("--window-hours", type=int, default=168)
    parser.add_argument("--current-window-hours", type=int, default=24)
    args = parser.parse_args(argv)
    try:
        config, now = Config.from_env(), utcnow()
        with connect(config.db_path) as con:
            start, end, _ = windows(now, args.current_window_hours, args.window_hours)
            backfill(con, config, start, end)
            snapshot = capture(con, config, args.pipeline_version, now,
                               args.current_window_hours, args.window_hours)
        print(json.dumps({k: v for k, v in snapshot.items() if k != "samples"}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
