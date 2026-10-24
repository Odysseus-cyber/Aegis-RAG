"""Publish explicitly synthetic fixtures without touching production SQLite.

python -m monitoring.drift_job.demo --scenario alert --output reports/demo-alert.json
"""
import argparse
import time

from monitoring.drift_job import feedback_analysis, output_drift, retrieval_drift
from monitoring.drift_job.common import Config, insufficient, result, write_json
from monitoring.drift_job.run_drift import publish, summarize


def fixture(shift=False, count=20):
    return {"messages": [{"id": f"synthetic-{i}", "retrieved_chunks": [{"score": 5 if shift else .9}],
                           "response_length": 1000 if shift else 100,
                           "embedding": [0, 1] if shift else [1, 0]} for i in range(count)],
            "feedback": [{"rating": -1 if shift else 1} for _ in range(count)]}


def build_report(scenario):
    reference = fixture()
    current = fixture(shift=scenario == "alert", count=2 if scenario == "insufficient_data" else 20)
    metrics = []
    for evaluator in [retrieval_drift.evaluate, output_drift.evaluate, feedback_analysis.evaluate]:
        metrics += evaluator(reference, current)
    for name, threshold in [("faithfulness", .7), ("answer_relevance", .65), ("context_precision", .6)]:
        if scenario == "insufficient_data":
            metrics.append(insufficient(name + "_mean", 0, reason="Synthetic empty quality dataset"))
        else:
            score = .3 if scenario == "alert" else .9
            metrics.append(result(name + "_mean", score, threshold, score < threshold, 20,
                                  method="synthetic_fixture_not_model_evaluation"))
    if scenario == "error":
        # Failed job replaces the whole group so no previous scores survive.
        metrics = [result("execution", status="error", reason="Synthetic model connection failure")]
    return summarize({"application": "Aegis-RAG", "source": "synthetic_demo",
                      "scenario": scenario, "timestamp": time.time(), "duration_seconds": 0,
                      "metrics": metrics})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aegis-RAG synthetic monitoring demonstration")
    parser.add_argument("--scenario", choices=["passed", "alert", "insufficient_data", "error"], required=True)
    parser.add_argument("--output", default="reports/drift-demo.json")
    args = parser.parse_args(argv)
    report = build_report(args.scenario)
    try:
        publish(Config.from_env(), report, source="synthetic_demo")
    except Exception as exc:
        report["metrics"].append(result("pushgateway", status="error", reason=str(exc)))
        summarize(report)
    write_json(args.output, report)
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
