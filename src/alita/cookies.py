from __future__ import annotations

from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

import httpx
from zendriver.cdp.network import Cookie as CdpCookie
from zendriver.cdp.network import CookieParam

from .models import CookieState


def cookie_matches(cookie: CdpCookie, url: str) -> bool:
    host = urlparse(url).hostname or ""
    if not host:
        return True
    domain = cookie.domain.lstrip(".")
    return not domain or host == domain or host.endswith(f".{domain}")


def cookie_state_from_cdp(cookie: CdpCookie) -> CookieState:
    return CookieState(
        name=cookie.name,
        value=cookie.value,
        domain=cookie.domain,
        path=cookie.path,
        secure=cookie.secure,
        http_only=cookie.http_only,
        expires=cookie.expires,
    )


def cookie_state_from_cookiejar(cookie: Any) -> CookieState:
    return CookieState(
        name=cookie.name,
        value=cookie.value,
        domain=cookie.domain,
        path=cookie.path,
        secure=cookie.secure,
        http_only=getattr(cookie, "_rest", {}).get("HttpOnly"),
        expires=cookie.expires,
    )


def cookie_state_to_param(cookie: CookieState, url: str) -> CookieParam:
    return CookieParam(
        name=cookie.name,
        value=cookie.value,
        url=url if not cookie.domain else None,
        domain=cookie.domain,
        path=cookie.path,
        secure=cookie.secure,
        http_only=cookie.http_only,
    )


def merge_cookies(existing: Sequence[CookieState], updates: Sequence[CookieState]) -> list[CookieState]:
    merged: dict[tuple[str, str, str], CookieState] = {cookie.key(): cookie for cookie in existing}
    for cookie in updates:
        merged[cookie.key()] = cookie
    return list(merged.values())


def cookies_for_request(cookies: Sequence[CookieState]) -> httpx.Cookies:
    jar = httpx.Cookies()
    for cookie in cookies:
        jar.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path or "/")
    return jar


def filter_cookie_states(cookies: Iterable[CookieState], url: str) -> list[CookieState]:
    host = urlparse(url).hostname or ""
    if not host:
        return list(cookies)
    filtered: list[CookieState] = []
    for cookie in cookies:
        domain = (cookie.domain or host).lstrip(".")
        if not domain or host == domain or host.endswith(f".{domain}"):
            filtered.append(cookie)
    return filtered
