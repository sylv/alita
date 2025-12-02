from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    host: str = os.getenv("ALITA_HOST", "0.0.0.0")
    port: int = int(os.getenv("ALITA_PORT", "4000"))
    disable_sandbox: bool = _env_bool("ALITA_DISABLE_SANDBOX", False)
    browser_headless: bool = _env_bool("ALITA_BROWSER_HEADLESS", False)
    browser_idle_shutdown_seconds: float = float(
        os.getenv("ALITA_BROWSER_IDLE_SECONDS", "10")
    )
    ready_state_timeout: float = float(os.getenv("ALITA_READY_STATE_TIMEOUT", "20"))
    ready_state_target: str = os.getenv("ALITA_READY_STATE_TARGET", "complete")
    http_timeout: float = float(os.getenv("ALITA_HTTP_TIMEOUT", "20"))


settings = Settings()
