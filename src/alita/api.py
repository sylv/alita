from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from .browser_pool import BrowserPool
from .config import settings
from .models import FetchRequest, SessionStore, domain_from_url
from .service import aggregate_headers, browser_flow, plain_flow


def create_app() -> FastAPI:
    session_store = SessionStore()
    browser_pool = BrowserPool(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = httpx.AsyncClient(follow_redirects=True, timeout=settings.http_timeout)
        app.state.http_client = client
        try:
            yield
        finally:
            await client.aclose()
            await browser_pool.shutdown()

    app = FastAPI(title="alita", lifespan=lifespan)

    @app.post("/get")
    async def fetch_endpoint(payload: FetchRequest, request: Request):
        client: httpx.AsyncClient = request.app.state.http_client
        domain = domain_from_url(str(payload.url))
        state = await session_store.get_state(domain)
        async with state.lock:
            if not state.initialized:
                result = await browser_flow(payload, state, domain, browser_pool, settings)
                state.initialized = True
            else:
                result = await plain_flow(payload, state, domain, browser_pool, settings, client)
            state.cookies = result.cookies
            if result.used_browser:
                state.request_headers = dict(result.request_headers)
            return {
                "status_code": result.status_code,
                "used_browser": result.used_browser,
                "headers": aggregate_headers(result.headers),
                "body": result.body,
            }

    return app
