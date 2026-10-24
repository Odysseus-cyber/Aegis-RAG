"""Seeded cosine drift and baseline-binned response length PSI."""
import random

import numpy as np

from monitoring.drift_job.common import finite, insufficient, result


def _mean_cosine_similarity(ref, cur):
    rng = random.Random(42)
    n = min(len(ref), len(cur), 200)
    a, b = np.array(rng.sample(ref, n)), np.array(rng.sample(cur, n))
    return float(np.mean(np.sum(a * b, axis=1) /
                         (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))))


def _psi(reference, current, bins=10):
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(edges) == 1:
        edges = np.array([-np.inf, edges[0] - .5, edges[0] + .5, np.inf])
    else:
        edges = np.concatenate(([-np.inf], edges, [np.inf]))
    a = np.histogram(reference, bins=edges)[0] + 1e-6
    b = np.histogram(current, bins=edges)[0] + 1e-6
    a, b = a / a.sum(), b / b.sum()
    return float(np.sum((b-a) * np.log(b/a)))


def embeddings(data):
    return [m["embedding"] for m in data["messages"] if m.get("embedding")
            and np.isfinite(m["embedding"]).all() and np.linalg.norm(m["embedding"]) > 0]


def evaluate(reference, current):
    ref, cur = embeddings(reference), embeddings(current)
    results = []
    if min(len(ref), len(cur)) < 10:
        results.append(insufficient("output_cosine_similarity_drop", len(cur), len(ref)))
    else:
        if len({len(v) for v in ref + cur}) != 1:
            raise ValueError("Embedding dimensions differ; capture a new baseline after model changes")
        self_similarity = _mean_cosine_similarity(ref, ref)
        similarity = _mean_cosine_similarity(ref, cur)
        drop = self_similarity - similarity
        results.append(result("output_cosine_similarity_drop", drop, .05, drop > .05,
                              len(cur), len(ref), reference_similarity=self_similarity,
                              mean_similarity=similarity))
    ref = finite([m.get("response_length") for m in reference["messages"]])
    cur = finite([m.get("response_length") for m in current["messages"]])
    if min(len(ref), len(cur)) < 10:
        results.append(insufficient("response_length_psi", len(cur), len(ref)))
    else:
        psi = _psi(ref, cur)
        results.append(result("response_length_psi", psi, .2, psi > .2, len(cur), len(ref)))
    return results
