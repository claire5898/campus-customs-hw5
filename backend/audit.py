"""Append-only JSON-array audit trail for observable agent workflow events."""

from __future__ import annotations

import fcntl
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


BACKEND_DIR = Path(__file__).resolve().parent
AUDIT_FILE = BACKEND_DIR.parent / "output" / "audit_trail.json"
_PROCESS_LOCK = threading.Lock()


def json_safe(value: Any) -> Any:
    """Convert Pydantic models and nested values to JSON-serializable data."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


class AuditTrail:
    """Append events to a persistent JSON array without discarding prior runs."""

    def __init__(self, path: Path = AUDIT_FILE, run_id: str | None = None) -> None:
        self.path = path
        self.run_id = run_id or str(uuid4())

    def append(self, event: str, **details: Any) -> dict[str, Any]:
        """Append one timestamped event and preserve all earlier events."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _PROCESS_LOCK:
            mode = "r+b" if self.path.exists() else "w+b"
            with self.path.open(mode) as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    stream.seek(0)
                    raw = stream.read()
                    if not raw.strip():
                        events: list[dict[str, Any]] = []
                    else:
                        events = json.loads(raw)
                        if not isinstance(events, list):
                            raise ValueError(
                                f"Audit file must contain a JSON array: {self.path}"
                            )
                    record = {
                        "sequence": len(events) + 1,
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "run_id": self.run_id,
                        "event": event,
                        **json_safe(details),
                    }

                    encoded_record = json.dumps(
                        record, ensure_ascii=False, indent=2
                    ).encode("utf-8")
                    if not raw.strip():
                        suffix = b"[\n" + encoded_record + b"\n]\n"
                        stream.seek(0)
                        stream.truncate()
                        stream.write(suffix)
                    else:
                        stripped = raw.rstrip()
                        closing = stripped.rfind(b"]")
                        if closing < 0 or stripped[closing + 1 :].strip():
                            raise ValueError(f"Audit JSON array is incomplete: {self.path}")
                        suffix = (
                            (b",\n" if events else b"")
                            + encoded_record
                            + b"\n]\n"
                        )
                        stream.seek(closing)
                        stream.truncate()
                        stream.write(suffix)
                    stream.flush()
                    os.fsync(stream.fileno())
                    return record
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def read_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        """Read the newest events without changing the persistent log."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if not self.path.exists():
            return []
        with _PROCESS_LOCK:
            with self.path.open("r", encoding="utf-8") as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
                try:
                    events = json.load(stream)
                    if not isinstance(events, list):
                        raise ValueError(f"Audit file must contain a JSON array: {self.path}")
                    return events[-limit:]
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
