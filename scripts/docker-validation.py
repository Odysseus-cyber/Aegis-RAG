#!/usr/bin/env python3
"""Prepare isolated Docker acceptance data, or check the running isolated stack.

Usage: python scripts/docker-validation.py prepare|check
The generated Compose file uses loopback-only alternate ports and copied data.
"""

import argparse
import json
import os
import shutil
import subprocess
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".runtime" / "docker-validation"
CONFIG = STATE / "compose.json"
PORTS = {
    "ollama": 21434, "chromadb": 18001, "backend": 18000,
    "frontend": 15173, "prometheus": 19090, "grafana": 13000,
    "pushgateway": 19091,
}


def prepare():
    config = json.loads(subprocess.check_output(
        ["docker", "compose", "config", "--format", "json"], cwd=ROOT,
    ))
    config["name"] = "ccrag-validation"
    for name, network in config.get("networks", {}).items():
        network["name"] = f"ccrag-validation_{name}"
    for name, service in config["services"].items():
        for port in service.get("ports", []):
            port.update(published=str(PORTS[name]), host_ip="127.0.0.1")
        for mount in service.get("volumes", []):
            source = Path(mount.get("source", ""))
            if mount["type"] != "bind":
                continue
            if source.parent == ROOT / "volumes" or source in (ROOT / "data", ROOT / "llms-txt"):
                destination = STATE / source.name
                if source.name in ("ollama", "data") and source.exists() and not destination.exists():
                    shutil.copytree(source, destination)
                else:
                    destination.mkdir(parents=True, exist_ok=True)
                mount["source"] = str(destination)
        if name == "backend":
            service["user"] = f"{os.getuid()}:{os.getgid()}"
    STATE.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Prepared {CONFIG.relative_to(ROOT)} (existing isolated data retained).")
    print("docker compose -f .runtime/docker-validation/compose.json up -d --build")
    print("python scripts/docker-validation.py check")
    print("docker compose -f .runtime/docker-validation/compose.json down")


def request(url, data=None):
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=600)


def check():
    base = "http://127.0.0.1:15173/api"
    for url in (
        base + "/health", "http://127.0.0.1:19090/-/ready",
        "http://127.0.0.1:13000/api/health", "http://127.0.0.1:19091/-/ready",
    ):
        with request(url) as response:
            assert response.status == 200, url
        print(f"PASS {url}")
    documents = None
    chunk_count = None
    for _ in range(2):
        with request(base + "/admin/ingest", {}) as response:
            assert response.status == 200
        with request(base + "/admin/documents") as response:
            current = json.load(response)["documents"]
        assert current, "No PDF documents indexed"
        assert documents is None or current == documents, "Repeated ingestion changed document list"
        documents = current
        count = int(subprocess.check_output([
            "docker", "compose", "-f", str(CONFIG), "exec", "-T", "backend",
            "python", "-c",
            "from app.rag.ingest import _chroma_client, _get_collection; "
            "print(_get_collection(_chroma_client()).count())",
        ], cwd=ROOT).strip())
        assert count > 0 and (chunk_count is None or count == chunk_count), "Repeated ingestion changed chunk count"
        chunk_count = count
    conversation = str(uuid.uuid4())
    history = []
    for query in ("Summarize the main topics of this document.", "Explain the first topic in more detail."):
        with request(base + "/chat", {
            "conversation_id": conversation, "message": query,
            "history": history, "doc_filter": documents,
        }) as response:
            message_id = response.headers["X-Message-Id"]
            stream = response.read().decode()
        assert "event: error" not in stream, stream
        assert "event: done" in stream and "event: citations" in stream, stream
        answer = "".join(json.loads(line[6:]).get("token", "")
                         for line in stream.splitlines()
                         if line.startswith('data: {'))
        assert answer.strip(), stream
        history.extend([{"role": "user", "content": query}, {"role": "assistant", "content": answer}])
        with request(base + "/feedback", {"message_id": message_id, "rating": 1}) as response:
            assert json.load(response)["feedback_id"]
    with request(base + f"/conversations/{conversation}") as response:
        assert len(json.load(response)["messages"]) == 4
    print("PASS repeated PDF ingestion, two proxied SSE turns, persistence and immediate feedback")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "check"))
    args = parser.parse_args()
    {"prepare": prepare, "check": check}[args.action]()
