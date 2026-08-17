"""RSS/Atom フィード取得（標準ライブラリの XML パーサのみ使用）。

フィード URL は config/personal.toml [news].feed_urls でオーナーが管理する。
条件付き GET（ETag/Last-Modified）を尊重し、失敗はコード付きで報告する。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

FETCH_TIMEOUT_SECONDS = 20.0
MAX_FEED_BYTES = 4 * 1024 * 1024
MAX_ITEMS_PER_FEED = 400
NEWS_USER_AGENT = "Mozilla/5.0 (compatible; OptixJapan-News/1.0)"


@dataclass(frozen=True)
class FeedItem:
    title: str
    link: str | None
    summary: str | None
    published_at: str | None  # ISO8601 UTC


@dataclass(frozen=True)
class FeedResult:
    feed_url: str
    status: str  # ok | not_modified | error
    error_code: str | None
    etag: str | None
    last_modified: str | None
    items: tuple[FeedItem, ...]


def _to_iso(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    try:
        parsed = parsedate_to_datetime(text)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _element_text(parent: ET.Element, *names: str) -> str | None:
    for child in parent:
        if _local_name(child.tag) in names:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _atom_link(parent: ET.Element) -> str | None:
    for child in parent:
        if _local_name(child.tag) == "link":
            href = child.get("href")
            if href:
                return href.strip()
            text = (child.text or "").strip()
            if text:
                return text
    return None


def parse_feed_xml(payload: bytes) -> list[FeedItem]:
    root = ET.fromstring(payload)
    items: list[FeedItem] = []
    entries = [node for node in root.iter() if _local_name(node.tag) in ("item", "entry")]
    for entry in entries[:MAX_ITEMS_PER_FEED]:
        title = _element_text(entry, "title")
        if not title:
            continue
        summary = _element_text(entry, "description", "summary", "content")
        link = _atom_link(entry)
        published = _to_iso(
            _element_text(entry, "pubdate", "published", "updated", "date")
        )
        items.append(FeedItem(title=title, link=link, summary=summary, published_at=published))
    return items


def fetch_feed(
    feed_url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> FeedResult:
    if not feed_url.startswith("https://"):
        return FeedResult(feed_url, "error", "feed_url_not_https", None, None, ())
    headers = {"User-Agent": NEWS_USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True, transport=transport) as client:
            response = client.get(feed_url, headers=headers)
    except httpx.TimeoutException:
        return FeedResult(feed_url, "error", "feed_timeout", etag, last_modified, ())
    except httpx.HTTPError:
        return FeedResult(feed_url, "error", "feed_transport_error", etag, last_modified, ())
    if response.status_code == 304:
        return FeedResult(feed_url, "not_modified", None, etag, last_modified, ())
    if response.status_code != 200:
        return FeedResult(feed_url, "error", f"feed_http_{response.status_code}", etag, last_modified, ())
    final_url = str(response.url)
    if not final_url.startswith("https://"):
        return FeedResult(feed_url, "error", "feed_redirect_not_https", etag, last_modified, ())
    if len(response.content) > MAX_FEED_BYTES:
        return FeedResult(feed_url, "error", "feed_too_large", etag, last_modified, ())
    try:
        items = parse_feed_xml(response.content)
    except ET.ParseError:
        return FeedResult(feed_url, "error", "feed_parse_error", etag, last_modified, ())
    return FeedResult(
        feed_url,
        "ok",
        None,
        response.headers.get("ETag"),
        response.headers.get("Last-Modified"),
        tuple(items),
    )


__all__ = ["FeedItem", "FeedResult", "fetch_feed", "parse_feed_xml"]
