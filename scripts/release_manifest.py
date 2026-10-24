"""Combine three successful image publications into one deployable release."""
import json
import os
import re
import sys
from pathlib import Path

REPOSITORY = "Odysseus-cyber/Aegis-RAG"
IMAGE_ROOT = "ghcr.io/odysseus-cyber/aegis-rag"
STORAGE_NAMESPACE = "aegis-rag-v2"


def validate_manifest(manifest, version=None):
    if manifest.get("storage_namespace") != STORAGE_NAMESPACE:
        raise ValueError("Incompatible storage namespace; use the archived migration restore procedure "
                         "for releases outside this namespace")
    sha = manifest["commit_sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or (version and sha != version):
        raise ValueError("Release commit does not match requested full SHA")
    if manifest.get("schema_version") != 1 or set(manifest["images"]) != {"backend", "frontend", "drift"}:
        raise ValueError("Incomplete or unsupported delivery manifest")
    for name, image in manifest["images"].items():
        if image["image"] != f"{IMAGE_ROOT}/{name}" or not re.fullmatch(r"sha256:[0-9a-f]{64}", image["digest"]):
            raise ValueError(f"Invalid image reference: {name}")
    return manifest


def assemble(directory, sha, actions_url):
    images = {name: json.loads((directory / f"{name}.json").read_text()) for name in ("backend", "frontend", "drift")}
    return validate_manifest({
        "schema_version": 1, "name": "Aegis-RAG", "commit_sha": sha,
        "storage_namespace": STORAGE_NAMESPACE,
        "actions_url": actions_url, "images": images,
        "deployment_asset": f"https://github.com/{REPOSITORY}/releases/download/sha-{sha}/deployment.tar.gz",
    })


if __name__ == "__main__":
    result = assemble(Path(sys.argv[1]), os.environ["COMMIT_SHA"], os.environ["ACTIONS_URL"])
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + "\n")
