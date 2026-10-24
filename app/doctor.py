"""Check the local runtime without changing the document collection."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

from app.config import settings
from app.pii import _get_analyzer


def main() -> None:
    errors: list[str] = []
    print(f"Python: {sys.version.split()[0]}")
    try:
        _get_analyzer()
        print("PII model: en_core_web_sm ready")
    except Exception as exc:
        errors.append(str(exc))
    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=10)
        response.raise_for_status()
        installed = {item['name'] for item in response.json()['models']}
        for name in [settings.llm_model, settings.embed_model]:
            tag = name if ':' in name else f'{name}:latest'
            if tag not in installed:
                errors.append(f"Missing model: run ollama pull {name}")
            else:
                print(f"Ollama model: {tag} ready")
    except Exception as exc:
        errors.append(f"Ollama unavailable at {settings.ollama_base_url}: {exc}")
    for value in [settings.telemetry_db_path, settings.llms_txt_dir,
                  *([settings.chroma_local_path] if settings.chroma_mode == 'local' else [])]:
        path = Path(value).resolve()
        while not path.exists():
            path = path.parent
        if not os.access(path, os.W_OK):
            errors.append(f"Not writable: {path}")
    print(f"ChromaDB: {settings.chroma_mode}")
    print(f"PDFs: {len(list(Path(settings.data_dir).glob('*.pdf')))}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        raise SystemExit(1)
    print("Ready. Run make ingest, then make backend and make frontend.")


if __name__ == '__main__':
    main()
