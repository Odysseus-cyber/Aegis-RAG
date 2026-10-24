"""Aegis-RAG drift reporting: 0 completed/skipped, 1 alert, 2 execution error."""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from urllib.request import Request, urlopen

from monitoring.drift_job import feedback_analysis, output_drift, quality_eval, retrieval_drift
from monitoring.drift_job.common import (
    Config,
    connect,
    load_window,
    result,
    utcnow,
    windows,
    write_json,
)
from monitoring.drift_job.snapshot import get_baseline

STATUS = {"passed": 0, "alert": 1, "insufficient_data": 2, "error": 3}


def summarize(report):
    statuses = {r["status"] for r in report["metrics"]}
    report["status"] = next((s for s in ["error", "alert", "insufficient_data"] if s in statuses), "passed")
    report["exit_code"] = 2 if "error" in statuses else int("alert" in statuses)
    return report


def metrics_text(report):
    lines = ["# TYPE ccrag_drift_status gauge", "# TYPE ccrag_drift_value gauge",
             "# TYPE ccrag_drift_breach gauge", "# TYPE ccrag_drift_samples gauge",
             "# TYPE ccrag_drift_run_timestamp_seconds gauge",
             "# TYPE ccrag_drift_run_duration_seconds gauge"]
    for metric in report["metrics"]:
        label = 'metric_name=' + json.dumps(metric["metric"])
        lines.append(f"ccrag_drift_status{{{label}}} {STATUS[metric['status']]}")
        for window, key in [("current", "current_n"), ("reference", "reference_n")]:
            lines.append(f'ccrag_drift_samples{{{label},window="{window}"}} {metric[key]}')
        # Unavailable values and breach flags are omitted, never emitted as zero.
        if metric["value"] is not None:
            lines.append(f"ccrag_drift_value{{{label}}} {metric['value']}")
        if metric["status"] in ("passed", "alert"):
            lines.append(f"ccrag_drift_breach{{{label}}} {int(metric['status'] == 'alert')}")
    lines.append(f"ccrag_drift_run_timestamp_seconds {report['timestamp']}")
    lines.append(f"ccrag_drift_run_duration_seconds {report['duration_seconds']}")
    return "\n".join(lines) + "\n"


def publish(config, report, source="real"):
    if not config.pushgateway:
        return
    request = Request(config.pushgateway.rstrip("/") + "/metrics/job/aegis_drift/source/" + source,
                      data=metrics_text(report).encode(), method="PUT",
                      headers={"Content-Type": "text/plain; version=0.0.4"})
    # PUT replaces the entire group, removing values from earlier successful runs.
    with urlopen(request, timeout=15) as response:
        response.read()


def persist(con, report):
    for metric in report["metrics"]:
        # The existing schema disallows null scores: skipped/error states live in JSON
        # and Pushgateway only, instead of polluting historical scores with fake zeroes.
        if metric["value"] is None:
            continue
        con.execute(
            "INSERT INTO drift_runs (id,triggered_by,pipeline_version,run_at,window_start,"
            "window_end,metric_name,metric_value,threshold,breached,details) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), report["trigger"], report["pipeline_version"], report["run_at"],
             report["window_start"], report["window_end"], metric["metric"], metric["value"],
             metric["threshold"], int(metric["status"] == "alert"), json.dumps(metric)),
        )
    con.commit()


def run(config, trigger="adhoc", pipeline_version=None, window_hours=24, now=None):
    started = time.monotonic()
    now = now or utcnow()
    reference_start, current_start, end = windows(now, window_hours)
    report = {"application": "Aegis-RAG", "source": "real", "id": str(uuid.uuid4()),
              "trigger": trigger, "pipeline_version": pipeline_version,
              "run_at": now.isoformat(), "timestamp": now.timestamp(),
              "window_start": current_start.isoformat(), "window_end": end.isoformat(),
              "metrics": []}
    try:
        with connect(config.db_path) as con:
            try:
                report["embeddings_backfilled"] = quality_eval.backfill(con, config, reference_start, end)
            except Exception as exc:
                con.rollback()
                raise RuntimeError(f"Embedding backfill failed: {exc}") from exc
            baseline = get_baseline(con, config, pipeline_version, now, window_hours)
            report["baseline"] = {k: v for k, v in baseline.items() if k != "samples"}
            current = load_window(con, current_start, end)
            for name, evaluator in [("retrieval", retrieval_drift.evaluate),
                                    ("output", output_drift.evaluate),
                                    ("feedback", feedback_analysis.evaluate)]:
                try:
                    report["metrics"].extend(evaluator(baseline["samples"], current))
                except Exception as exc:
                    report["metrics"].append(result(name, status="error", reason=str(exc)))
            try:
                report["metrics"].extend(quality_eval.evaluate(con, config, current, report["id"]))
            except Exception as exc:
                con.rollback()
                report["metrics"].append(result("quality_eval", status="error", reason=str(exc)))
            persist(con, report)
    except Exception as exc:
        report["metrics"].append(result("execution", status="error", reason=str(exc)))
    report["duration_seconds"] = time.monotonic() - started
    summarize(report)
    try:
        publish(config, report)
    except Exception as exc:
        report["metrics"].append(result("pushgateway", status="error", reason=str(exc)))
    return summarize(report)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run Aegis-RAG drift and quality reporting")
    parser.add_argument("--trigger", choices=["cron", "ci", "adhoc"], required=True)
    parser.add_argument("--pipeline-version")
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--report", default=os.getenv("DRIFT_REPORT_PATH", "reports/drift.json"))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.window_hours <= 0:
        raise SystemExit("--window-hours must be positive")
    report = run(Config.from_env(), args.trigger, args.pipeline_version, args.window_hours)
    try:
        write_json(args.report, report)
    except Exception as exc:
        report["metrics"].append(result("report_write", status="error", reason=str(exc)))
        summarize(report)
    print(json.dumps(report, indent=2, allow_nan=False))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
