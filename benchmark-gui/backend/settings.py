"""Central Settings object — A5 in AUDIT.md.

Reads all environment-driven configuration once at import time and exposes
typed attributes. Replaces scattered `os.environ.get(...)` calls in
fastapi_app.

Plain dataclass instead of pydantic-settings to avoid adding a dependency
for two env vars; switch when more settings appear.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


_DEFAULT_ORIGINS = (
    "http://localhost:50072,"
    "http://127.0.0.1:50072,"
    "http://localhost:3000,"
    "http://127.0.0.1:3000"
)


def _parse_origins(raw: str) -> tuple[bool, List[str]]:
    if raw.strip() == "*":
        return True, ["*"]
    return False, [o.strip() for o in raw.split(",") if o.strip()]


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    allow_all_origins: bool
    allowed_origins: List[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.environ.get("BENCHMARK_API_KEY") or None
        raw_origins = os.environ.get("BENCHMARK_ALLOWED_ORIGINS", _DEFAULT_ORIGINS)
        allow_all, origins = _parse_origins(raw_origins)
        return cls(
            api_key=api_key,
            allow_all_origins=allow_all,
            allowed_origins=origins or ["http://localhost:50072"],
        )


settings = Settings.from_env()
