"""Shared configuration and frozen, nonoverlapping evaluation windows."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings


@dataclass
class Config:
    db_path: str = settings.telemetry_db_path
    ollama_url: str = settings.ollama_base_url
    llm_model: str = settings.llm_model
    embed_model: str = settings.embed_model
    baseline_path: str = ""
    pushgateway: str = ""
    sample_size: int = 10
    reference_dataset: str = ""

    @classmethod
    def from_env(cls):
        db = os.getenv("TELEMETRY_DB_PATH", settings.telemetry_db_path)
        return cls(
            db_path=db,
            baseline_path=os.getenv("DRIFT_BASELINE_PATH", str(Path(db).parent / "baseline.json")),
            pushgateway=os.getenv("PUSHGATEWAY_URL", ""),
            sample_size=int(os.getenv("DRIFT_QUALITY_SAMPLE_SIZE", "10")),
            reference_dataset=os.getenv("DRIFT_REFERENCE_DATASET", ""),
        )


def connect(path):
    # Never silently create an empty DB after a configuration typo.
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def utcnow():
    return datetime.now(timezone.utc)


def windows(now, hours=24, reference_hours=168):
    end = now - timedelta(hours=hours)
    return end - timedelta(hours=reference_hours), end, now


def load_window(con, start, end):
    args = (start.isoformat(), end.isoformat())
    rows = con.execute(
        "SELECT * FROM messages WHERE role='assistant' AND julianday(created_at)>=julianday(?) "
        "AND julianday(created_at)<julianday(?) ORDER BY created_at,id", args,
    ).fetchall()
    messages = []
    for row in rows:
        msg = dict(row)
        blob = msg.pop("response_embedding")
        msg.pop("query_embedding", None)
        msg["embedding"] = list(struct.unpack(f"{len(blob)//4}f", blob)) if blob else None
        msg["retrieved_chunks"] = json.loads(msg["retrieved_chunks"] or "[]")
        messages.append(msg)
    feedback = [dict(row) for row in con.execute(
        "SELECT rating FROM feedback WHERE julianday(created_at)>=julianday(?) "
        "AND julianday(created_at)<julianday(?) ORDER BY created_at,id", args,
    )]
    return {"messages": messages, "feedback": feedback}


def finite(values):
    return [float(v) for v in values if v is not None and math.isfinite(float(v))]


def result(name, value=None, threshold=None, breach=False, current_n=0, reference_n=0,
           reason=None, status=None, **details):
    return {"metric": name, "status": status or ("alert" if breach else "passed"),
            "value": value, "threshold": threshold, "current_n": current_n,
            "reference_n": reference_n, "reason": reason, "details": details}


def insufficient(name, current_n, reference_n=0, reason="At least 10 valid samples per window required"):
    return result(name, current_n=current_n, reference_n=reference_n,
                  status="insufficient_data", reason=reason)


def write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False))
    temporary.replace(target)
