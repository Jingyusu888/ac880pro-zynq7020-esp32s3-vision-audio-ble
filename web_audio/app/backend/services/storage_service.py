from __future__ import annotations

from datetime import datetime
from uuid import uuid4


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_id(prefix: str) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f")
    return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"

