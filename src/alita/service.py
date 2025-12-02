from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
from typing import Mapping

import httpx
from fastapi import HTTPException
from zendriver import cdp
from zendriver.cdp.fetch import HeaderEntry, RequestStage
from zendriver.cdp.network import ResourceType
from zendriver.core.tab import Tab

from .browser_pool import BrowserPool
from .config import Settings
from .cookies import (
    cookie_state_from_cookiejar,
    cookies_for_request,
    filter_cookie_states,
    merge_cookies,
)
from .models import (
    BrowserResponseInfo,
    FetchRequest,
    PageResult,
    PlainSnapshot,
    SessionState,
)
from .selectors import evaluate_plain_html

HOP_BY_HOP_HEADERS = {
    "host",
    "connection",
    "proxy-connection",
    "content-length",
    "accept-encoding",
    "upgrade",
    "upgrade-insecure-requests",
    "te",
    "trailers",
    "transfer-encoding",
}

logger = logging.getLogger(__name__)


def headers_from_httpx(headers: httpx.Headers) -> list[tuple[str, str]]:
    return [(name, value) for name, value in headers.multi_items()]


def headers_from_mapping(headers: Mapping[str, str]) -> list[tuple[str, str]]:
    return [(name, value) for name, value in headers.items()]


def aggregate_headers(headers: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"name": name.lower(), "value": value} for name, value in headers]


def sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    sanitized = {}
    for key, value in headers.items():
        if key.lower() in HOP_BY_HOP_HEADERS:
            continue
        sanitized[key] = value
    return sanitized


def extract_user_agent(headers: Mapping[str, str]) -> str | None:
    for key in ("user-agent", "User-Agent"):
        if key in headers:
            return headers[key]
    return None


async def await_rendered_html(tab: Tab, selector: str, payload: FetchRequest, settings: Settings) -> str:
    ready_timeout = max(payload.wait_timeout, settings.ready_state_timeout)
    target_url = str(payload.url)
    logger.debug(
        "Waiting for ready state '%s' on %s (timeout %.1fs)",
        settings.ready_state_target,
        target_url,
        ready_timeout,
    )
    try:
        await asyncio.wait_for(
            tab.wait_for_ready_state(settings.ready_state_target, timeout=int(ready_timeout)),
            timeout=ready_timeout,
        )
    except asyncio.TimeoutError as exc:
        logger.warning(
            "Timed out waiting for ready state '%s' on %s after %.1fs",
            settings.ready_state_target,
            target_url,
            ready_timeout,
        )
        raise HTTPException(status_code=504, detail="Timed out waiting for ready state") from exc
    logger.debug("Ready state '%s' satisfied on %s", settings.ready_state_target, target_url)
    logger.debug("Waiting for selector '%s' on %s (timeout %.1fs)", selector, target_url, payload.wait_timeout)
    try:
        await asyncio.wait_for(
            tab.wait_for(selector=selector, timeout=payload.wait_timeout),
            timeout=payload.wait_timeout,
        )
    except asyncio.TimeoutError as exc:
        logger.warning(
            "Timed out waiting for selector '%s' on %s after %.1fs",
            selector,
            target_url,
            payload.wait_timeout,
        )
        raise HTTPException(status_code=504, detail="Timed out waiting for wait_for_element") from exc
    html = await tab.get_content()
    logger.debug("Rendered HTML ready for %s (length=%d)", target_url, len(html))
    return html


async def hydrate_with_snapshot(tab: Tab, url: str, snapshot: PlainSnapshot) -> None:
    async with tab.intercept(r".*", RequestStage.REQUEST, ResourceType.DOCUMENT) as interception:
        await tab.send(cdp.page.navigate(url))
        await interception.response_future
        header_entries = [HeaderEntry(name=name, value=value) for name, value in snapshot.headers]
        body_b64 = base64.b64encode(snapshot.body).decode("ascii")
        await interception.fulfill_request(
            response_code=snapshot.status_code,
            response_headers=header_entries,
            body=body_b64,
        )


async def capture_browser_navigation(
    tab: Tab,
    page_ready: asyncio.Event,
    navigation_frame: asyncio.Future[cdp.page.FrameId],
) -> BrowserResponseInfo:
    """Capture the final top-level Document response for the current navigation."""

    request_headers_map: dict[cdp.network.RequestId, dict[str, str]] = {}
    document_available = asyncio.Event()
    document_events: list[tuple[cdp.page.FrameId, int, list[tuple[str, str]], dict[str, str]]] = []

    async def handle_request(event: cdp.network.RequestWillBeSent) -> None:
        if event.type_ != ResourceType.DOCUMENT:
            return
        request_headers_map[event.request_id] = dict(event.request.headers)

    async def handle_response(event: cdp.network.ResponseReceived) -> None:
        if event.type_ != ResourceType.DOCUMENT:
            return
        headers = headers_from_mapping(event.response.headers)
        document_events.append(
            (
                event.frame_id,
                event.response.status,
                headers,
                request_headers_map.pop(event.request_id, {}),
            )
        )
        document_available.set()

    tab.add_handler(cdp.network.RequestWillBeSent, handle_request)
    tab.add_handler(cdp.network.ResponseReceived, handle_response)

    try:
        frame_id = await navigation_frame
        await document_available.wait()
        await page_ready.wait()

        selected: tuple[cdp.page.FrameId, int, list[tuple[str, str]], dict[str, str]] | None = None
        for entry in reversed(document_events):
            if entry[0] == frame_id:
                selected = entry
                break
        if selected is None:
            selected = document_events[-1]

        _, status_code, headers, request_headers = selected
        return BrowserResponseInfo(
            status_code=status_code,
            headers=headers,
            request_headers=request_headers,
        )
    finally:
        tab.remove_handlers(cdp.network.RequestWillBeSent, handle_request)
        tab.remove_handlers(cdp.network.ResponseReceived, handle_response)


async def browser_flow(
    payload: FetchRequest,
    state: SessionState,
    domain: str,
    pool: BrowserPool,
    settings: Settings,
    snapshot: PlainSnapshot | None = None,
) -> PageResult:
    url = str(payload.url)
    logger.info(
        "Using browser pipeline for %s (%s)",
        domain,
        "snapshot replay" if snapshot else "live navigation",
    )
    manager = await pool.get(domain)
    async with manager.tab(state.cookies, url) as tab:
        capture_task: asyncio.Task[BrowserResponseInfo] | None = None
        page_ready: asyncio.Event | None = None
        response_info: BrowserResponseInfo | None = None
        if snapshot is None:
            loop = asyncio.get_running_loop()
            page_ready = asyncio.Event()
            navigation_frame: asyncio.Future[cdp.page.FrameId] = loop.create_future()
            capture_task = asyncio.create_task(
                capture_browser_navigation(tab, page_ready, navigation_frame)
            )
            try:
                frame_id, _, error_text = await tab.send(cdp.page.navigate(url))
            except Exception as exc:  # noqa: BLE001 - propagate after cleanup
                if not navigation_frame.done():
                    navigation_frame.set_exception(exc)
                capture_task.cancel()
                with contextlib.suppress(Exception):
                    await capture_task
                raise
            if error_text:
                err = RuntimeError(f"Navigation failed for {url}: {error_text}")
                if not navigation_frame.done():
                    navigation_frame.set_exception(err)
                capture_task.cancel()
                with contextlib.suppress(Exception):
                    await capture_task
                raise HTTPException(status_code=502, detail=str(err))
            navigation_frame.set_result(frame_id)
        else:
            await hydrate_with_snapshot(tab, url, snapshot)
            response_info = BrowserResponseInfo(
                status_code=snapshot.status_code,
                headers=snapshot.headers,
                request_headers=snapshot.request_headers,
            )
            page_ready = None
            logger.debug("Hydrated snapshot for %s with status %s", url, snapshot.status_code)

        try:
            html = await await_rendered_html(tab, payload.wait_for_element, payload, settings)
        except Exception:
            if page_ready:
                page_ready.set()
            if capture_task:
                capture_task.cancel()
                with contextlib.suppress(Exception):
                    await capture_task
            raise
        else:
            if page_ready:
                page_ready.set()
            if capture_task:
                response_info = await capture_task
                logger.debug(
                    "Captured browser response for %s with status %s",
                    url,
                    response_info.status_code,
                )
        if response_info is None:
            raise RuntimeError("Failed to capture browser response information")

        if snapshot is None:
            effective_headers: Mapping[str, str] = response_info.request_headers
        else:
            effective_headers = state.request_headers or snapshot.request_headers
        cookies = await manager.export_cookies(url)
        logger.debug("Exported %d cookies after browser run for %s", len(cookies), domain)
    filtered_cookies = filter_cookie_states(cookies, url)
    logger.info(
        "Browser pipeline complete for %s (status %s, used_browser=True)",
        domain,
        response_info.status_code,
    )
    return PageResult(
        status_code=response_info.status_code,
        headers=response_info.headers,
        body=html,
        used_browser=True,
        request_headers=dict(effective_headers),
        cookies=filtered_cookies,
    )


async def plain_flow(
    payload: FetchRequest,
    state: SessionState,
    domain: str,
    pool: BrowserPool,
    settings: Settings,
    client: httpx.AsyncClient,
) -> PageResult:
    url = str(payload.url)
    logger.debug("Attempting plain HTTP fetch for %s (domain=%s)", url, domain)
    if not state.request_headers:
        logger.info("No stored headers for %s; falling back to browser immediately", domain)
        return await browser_flow(payload, state, domain, pool, settings)

    headers = sanitize_headers(state.request_headers)
    cookies = cookies_for_request(state.cookies)
    try:
        response = await client.get(url, headers=headers, cookies=cookies)
    except httpx.HTTPError as exc:
        logger.warning("Plain HTTP request to %s failed (%s); falling back to browser", url, exc)
        return await browser_flow(payload, state, domain, pool, settings)

    header_list = headers_from_httpx(response.headers)
    cookie_updates = [cookie_state_from_cookiejar(cookie) for cookie in response.cookies.jar]
    merged_cookies = merge_cookies(state.cookies, cookie_updates)
    filtered_cookies = filter_cookie_states(merged_cookies, url)

    wait_present, blocking_selector = evaluate_plain_html(
        response.text, payload.wait_for_element, payload.browser_on_elements
    )
    fallback = False
    if not wait_present:
        logger.info(
            "Falling back to browser for %s because wait selector '%s' was not present",
            domain,
            payload.wait_for_element,
        )
        fallback = True
    if blocking_selector:
        logger.info(
            "Falling back to browser for %s because blocking selector '%s' matched",
            domain,
            blocking_selector,
        )
        fallback = True
    if fallback:
        snapshot = PlainSnapshot(
            status_code=response.status_code,
            headers=header_list,
            body=response.content,
            request_headers=headers,
        )
        state.cookies = filtered_cookies
        return await browser_flow(payload, state, domain, pool, settings, snapshot)

    logger.debug("Plain flow succeeded for %s (status=%s)", url, response.status_code)
    return PageResult(
        status_code=response.status_code,
        headers=header_list,
        body=response.text,
        used_browser=False,
        request_headers=state.request_headers,
        cookies=filtered_cookies,
    )
