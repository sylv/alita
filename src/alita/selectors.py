from __future__ import annotations

from typing import Sequence

from cssselect.parser import SelectorSyntaxError
from fastapi import HTTPException
from parsel import Selector


def selector_exists(doc: Selector, selector: str, label: str) -> bool:
    try:
        return bool(doc.css(selector))
    except SelectorSyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSS selector for {label}: {selector}") from exc


def evaluate_plain_html(
    html: str, wait_selector: str, browser_on: Sequence[str]
) -> tuple[bool, str | None]:
    doc = Selector(text=html)
    wait_present = selector_exists(doc, wait_selector, "wait_for_element") if wait_selector else False
    block_selector = next(
        (selector for selector in browser_on if selector_exists(doc, selector, "browser_on_elements")),
        None,
    )
    return wait_present, block_selector
