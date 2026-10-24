"""Deterministic two-window Kolmogorov–Smirnov retrieval test."""
from scipy.stats import ks_2samp

from monitoring.drift_job.common import finite, insufficient, result


def scores(data):
    return finite([m["retrieved_chunks"][0].get("score") for m in data["messages"]
                   if m["retrieved_chunks"]])


def evaluate(reference, current):
    ref, cur = scores(reference), scores(current)
    if min(len(ref), len(cur)) < 10:
        return [insufficient("retrieval_ks_pvalue", len(cur), len(ref))]
    stat, p = ks_2samp(ref, cur, method="auto")
    return [result("retrieval_ks_pvalue", float(p), .01, p < .01,
                   len(cur), len(ref), ks_statistic=float(stat))]
