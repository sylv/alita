from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Sequence
from contextlib import asynccontextmanager

from zendriver import Browser, cdp
from zendriver.core.tab import Tab

from .config import Settings
from .cookies import cookie_state_to_param, cookie_state_from_cdp, cookie_matches
from .models import CookieState


class BrowserManager:
    def __init__(self, config: Settings, domain: str) -> None:
        self._config = config
        self._domain = domain
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._active_tabs = 0
        self._last_used = 0.0
        self._shutdown_task: asyncio.Task[None] | None = None

    @property
    def domain(self) -> str:
        return self._domain

    @asynccontextmanager
    async def tab(self, cookies: Sequence[CookieState], url: str):
        tab = await self._acquire_tab(cookies, url)
        try:
            yield tab
        finally:
            await self._release_tab(tab)

    async def _acquire_tab(self, cookies: Sequence[CookieState], url: str) -> Tab:
        async with self._lock:
            browser = await self._ensure_browser()
            self._active_tabs += 1
        tab = await browser.get("about:blank", new_tab=True)
        await _enable_default_domains(tab)
        if cookies:
            params = [cookie_state_to_param(cookie, url) for cookie in cookies]
            await browser.cookies.set_all(params)
        return tab

    async def _release_tab(self, tab: Tab) -> None:
        try:
            await tab.close()
        except Exception:
            pass
        async with self._lock:
            self._active_tabs = max(0, self._active_tabs - 1)
            self._last_used = time.monotonic()
            if self._active_tabs == 0:
                self._schedule_shutdown()

    async def _ensure_browser(self) -> Browser:
        if self._browser:
            return self._browser
        browser_args = [
            "--disable-dev-shm-usage",
            "--disable-popup-blocking",
            "--disable-background-timer-throttling",
            "--no-default-browser-check",
        ]
        if self._config.browser_headless:
            browser_args.append("--headless=new")

        browser = await Browser.create(
            headless=self._config.browser_headless,
            sandbox=not self._config.disable_sandbox,
            browser_args=browser_args,
        )
        self._browser = browser
        self._last_used = time.monotonic()
        return browser

    def _schedule_shutdown(self) -> None:
        if self._shutdown_task and not self._shutdown_task.done():
            return
        self._shutdown_task = asyncio.create_task(self._shutdown_when_idle())

    async def _shutdown_when_idle(self) -> None:
        try:
            await asyncio.sleep(self._config.browser_idle_shutdown_seconds)
            async with self._lock:
                idle = (
                    time.monotonic() - self._last_used >= self._config.browser_idle_shutdown_seconds
                )
                if self._browser and self._active_tabs == 0 and idle:
                    await self._browser.stop()
                    self._browser = None
        except asyncio.CancelledError:
            raise

    async def shutdown(self) -> None:
        if self._shutdown_task:
            self._shutdown_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._shutdown_task
        async with self._lock:
            if self._browser:
                await self._browser.stop()
                self._browser = None

    async def export_cookies(self, url: str) -> list[CookieState]:
        browser = self._browser
        if not browser:
            return []
        cdp_cookies = await browser.cookies.get_all()
        return [cookie_state_from_cdp(cookie) for cookie in cdp_cookies if cookie_matches(cookie, url)]


class BrowserPool:
    def __init__(self, config: Settings) -> None:
        self._config = config
        self._managers: dict[str, BrowserManager] = {}
        self._lock = asyncio.Lock()

    async def get(self, domain: str) -> BrowserManager:
        async with self._lock:
            manager = self._managers.get(domain)
            if manager is None:
                manager = BrowserManager(self._config, domain)
                self._managers[domain] = manager
            return manager

    async def shutdown(self) -> None:
        async with self._lock:
            managers = list(self._managers.values())
            self._managers.clear()
        await asyncio.gather(*(manager.shutdown() for manager in managers), return_exceptions=True)


async def _enable_default_domains(tab: Tab) -> None:
    await tab.send(cdp.network.enable())
    await tab.send(cdp.page.enable())
    await tab.send(cdp.dom.enable())
