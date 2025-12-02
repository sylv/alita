from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from collections.abc import Iterable
from typing import Any, Mapping
from urllib.parse import urlparse

from pydantic import BaseModel, Field, HttpUrl, field_validator


class FetchRequest(BaseModel):
    url: HttpUrl
    wait_for_element: str | None = Field(default=None, min_length=1)
    browser_on_elements: list[str] = Field(default_factory=list)
    wait_timeout: float = Field(default=10.0, gt=0, le=120)

    @field_validator("browser_on_elements", mode="before")
    @classmethod
    def _ensure_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, Iterable):
            return list(value)
        raise TypeError("browser_on_elements must be a string or iterable of strings")

    @field_validator("browser_on_elements")
    @classmethod
    def _strip_entries(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @field_validator("wait_for_element")
    @classmethod
    def _strip_wait(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


@dataclass(slots=True)
class CookieState:
    name: str
    value: str
    domain: str | None = None
    path: str | None = None
    secure: bool | None = None
    http_only: bool | None = None
    expires: float | None = None

    def key(self) -> tuple[str, str, str]:
        domain = (self.domain or "").lstrip(".")
        path = self.path or "/"
        return (self.name, domain, path)


@dataclass
class SessionState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cookies: list[CookieState] = field(default_factory=list)
    initialized: bool = False
    request_headers: dict[str, str] | None = None


class SessionStore:
    def __init__(self) -> None:
        self._states: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def get_state(self, domain: str) -> SessionState:
        async with self._lock:
            state = self._states.get(domain)
            if state is None:
                state = SessionState()
                self._states[domain] = state
            return state


@dataclass
class PlainSnapshot:
    status_code: int
    headers: list[tuple[str, str]]
    body: bytes
    request_headers: Mapping[str, str]


@dataclass
class PageResult:
    status_code: int
    headers: list[tuple[str, str]]
    body: str
    used_browser: bool
    request_headers: Mapping[str, str]
    cookies: list[CookieState]


@dataclass
class BrowserResponseInfo:
    status_code: int
    headers: list[tuple[str, str]]
    request_headers: Mapping[str, str]


def domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or parsed.netloc or ""
    return host.lower()
