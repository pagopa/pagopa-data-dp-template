from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    env: str
    log_level: str = "INFO"
    write_enabled: bool = True
