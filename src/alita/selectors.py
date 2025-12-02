from __future__ import annotations

from typing import Sequence

from cssselect.parser import SelectorSyntaxError
from fastapi import HTTPException
from parsel import Selector

CLOUDFLARE_CHALLENGE_SELECTORS: tuple[str, ...] = (
    "#challenge-running",
    "#challenge-body-text",
    "#challenge-stage",
    "#cf-spinner-please-wait",
    ".cf-browser-verification",
    "form#challenge-form",
    "div[data-translate='checking_browser']",
)

CLOUDFLARE_TEXT_MARKERS: tuple[str, ...] = (
    "checking if the site connection is secure",
    "checking your browser before accessing",
    "enable javascript and cookies",
    "just a moment"
)


def selector_exists(doc: Selector, selector: str, label: str) -> bool:
    try:
        return bool(doc.css(selector))
    except SelectorSyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSS selector for {label}: {selector}") from exc


def detect_cloudflare_challenge(doc: Selector) -> str | None:
    for selector in CLOUDFLARE_CHALLENGE_SELECTORS:
        if selector_exists(doc, selector, "cloudflare_challenge"):
            return selector
    text = (doc.xpath("string()").get() or "").lower()
    for marker in CLOUDFLARE_TEXT_MARKERS:
        if marker in text:
            return marker
    return None


def detect_cloudflare_challenge_from_html(html: str) -> str | None:
    doc = Selector(text=html)
    return detect_cloudflare_challenge(doc)


def evaluate_plain_html(
    html: str, wait_selector: str | None, browser_on: Sequence[str]
) -> tuple[bool, str | None, str | None]:
    doc = Selector(text=html)
    wait_present = True
    if wait_selector:
        wait_present = selector_exists(doc, wait_selector, "wait_for_element")
    block_selector = next(
        (selector for selector in browser_on if selector_exists(doc, selector, "browser_on_elements")),
        None,
    )
    cloudflare_marker = detect_cloudflare_challenge(doc)
    return wait_present, block_selector, cloudflare_marker
