"""Feedback rates with minimum support and explicit zero-baseline policy."""
from monitoring.drift_job.common import insufficient, result


def evaluate(reference, current):
    ref, cur = reference["feedback"], current["feedback"]
    if min(len(ref), len(cur)) < 10:
        return [insufficient("feedback_thumbsdown_ratio", len(cur), len(ref))]
    baseline = sum(f["rating"] == -1 for f in ref) / len(ref)
    ratio = sum(f["rating"] == -1 for f in cur) / len(cur)
    threshold = 2 * baseline if baseline else .2
    return [result("feedback_thumbsdown_ratio", ratio, threshold, ratio >= threshold,
                   len(cur), len(ref), baseline_ratio=baseline)]
