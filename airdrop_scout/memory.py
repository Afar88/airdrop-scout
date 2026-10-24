"""Tiny JSON seen-store so daily runs only brief new campaigns."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("SCOUT_SEEN_FILE", Path(__file__).resolve().parent.parent / "seen.json"))


class SeenStore:
    def __init__(self, path: Path | str = DEFAULT_PATH, cap: int = 1000):
        self.path = Path(path)
        self.cap = cap

    def load(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text())
            return [str(x) for x in data] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def has(self, code: str) -> bool:
        return code in self.load()

    def add(self, code: str) -> bool:
        items = self.load()
        if code in items:
            return False
        items.append(code)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(items[-self.cap:], indent=0))
        return True
