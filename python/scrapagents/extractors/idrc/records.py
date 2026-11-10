"""Parse IDRC funding calls from the RSS feed, the HTML listing and detail pages.

What: pure functions (bytes in, dicts out), no network and no storage. Why: the call text
and fields come from two renderings of the same Drupal content (the RSS ``description`` holds
the rendered page, the detail page is the page itself), so one field parser reads both and a
record has the same shape whichever path produced it. Where: used by ``extractor`` and unit-tested
against saved samples of the real site.

No LLM and no dynamic selectors: every rule below is a fixed XML element or Drupal field class.
Personal data (design decisions of Gate H2): the contact email (``field-award-poc``) and the RSS
``dc:creator`` are never read, and emails inside the call text are replaced by a placeholder.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

DETAIL_PATH_PREFIX = "/en/funding/"
EMAIL_PLACEHOLDER = "[email redacted]"
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]*$")
_GUID_RE = re.compile(r"^\s*(\d+)\s+at\s+")
_BLOCK_TAGS = ("p", "li", "ul", "ol", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table")
_STOP_MARKERS = ("g-recaptcha", "h-captcha", "cf-turnstile", "captcha-delivery")
_WAF_MARKERS = ("just a moment...", "attention required", "access denied", "request unsuccessful")

SECTION_OPEN = "open"
SECTION_CLOSED = "closed"


class IdrcParseError(RuntimeError):
    """The source answered, but not with the structure the parser knows."""


@dataclass(frozen=True)
class FeedItem:
    slug: str
    url: str
    node_id: str | None
    title: str
    published_at: str | None
    html: str


@dataclass(frozen=True)
class ListingEntry:
    slug: str
    url_path: str
    title: str
    section: str
    call_type: str | None
    deadline: str | None


def detect_block(status: int | None, body: bytes) -> str | None:
    """Classify an anti-bot barrier from a response, or ``None`` when it looks open."""

    text = body[:200_000].decode("utf-8", errors="ignore").lower()
    if any(marker in text for marker in _STOP_MARKERS):
        return "captcha"
    if status in (403, 429) or any(marker in text for marker in _WAF_MARKERS):
        return "waf"
    return None


def redact_emails(text: str) -> str:
    """Replace every email address in ``text`` by a placeholder."""

    return _EMAIL_RE.sub(EMAIL_PLACEHOLDER, text)


def slug_from_url(url_or_path: str) -> str | None:
    """Slug of ``/en/funding/<slug>``, or ``None`` for any other URL (feed, listing, ...)."""

    path = urlparse(url_or_path).path.rstrip("/")
    if not path.startswith(DETAIL_PATH_PREFIX):
        return None
    slug = path[len(DETAIL_PATH_PREFIX) :]
    if "/" in slug or "." in slug or not _SLUG_RE.fullmatch(slug):
        return None
    return slug


def _clean(text: str) -> str:
    return " ".join(text.split())


def _to_utc(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _soup(content: bytes | str) -> BeautifulSoup:
    return BeautifulSoup(content, "html.parser")


def parse_feed(xml_bytes: bytes) -> list[FeedItem]:
    """Items of the RSS 2.0 feed. ``dc:creator`` (a staff email) is never read."""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise IdrcParseError(f"The IDRC feed is not valid XML: {exc}") from exc
    channel = root.find("channel")
    if channel is None:
        raise IdrcParseError("The IDRC feed has no <channel>.")
    items: list[FeedItem] = []
    for item in channel.findall("item"):
        link = (item.findtext("link") or "").strip()
        slug = slug_from_url(link)
        if slug is None:
            raise IdrcParseError(f"Feed item link {link!r} is not a /en/funding/<slug> URL.")
        guid = _GUID_RE.match(item.findtext("guid") or "")
        published = None
        raw_date = (item.findtext("pubDate") or "").strip()
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date).astimezone(UTC).isoformat()
            except (TypeError, ValueError):
                published = None
        items.append(
            FeedItem(
                slug=slug,
                url=link,
                node_id=guid.group(1) if guid else None,
                title=_clean(item.findtext("title") or ""),
                published_at=published,
                html=item.findtext("description") or "",
            )
        )
    return items


def parse_listing(html: bytes) -> list[ListingEntry]:
    """Calls of the HTML listing, each with the section (open or closed) it appears in."""

    soup = _soup(html)
    section: str | None = None
    entries: list[ListingEntry] = []
    for element in soup.find_all(["h2", "div"]):
        if element.name == "h2":
            heading = _clean(element.get_text()).lower()
            if heading == "open calls":
                section = SECTION_OPEN
            elif heading == "closed calls":
                section = SECTION_CLOSED
            continue
        if "views-row" not in (element.get("class") or []) or section is None:
            continue
        anchor = element.select_one(".views-field-title a[href]")
        if anchor is None:
            continue
        slug = slug_from_url(str(anchor["href"]))
        if slug is None:
            continue
        call_for = element.select_one(".views-field-field-award-call-for .field-content")
        deadline = element.select_one(".views-field-field-award-deadline time[datetime]")
        entries.append(
            ListingEntry(
                slug=slug,
                url_path=urlparse(str(anchor["href"])).path,
                title=_clean(anchor.get_text()),
                section=section,
                call_type=_clean(call_for.get_text()) if call_for else None,
                deadline=_to_utc(str(deadline["datetime"])) if deadline else None,
            )
        )
    return entries


def _field(soup: BeautifulSoup, name: str) -> Tag | None:
    return soup.select_one(f".field--name-{name}")


def _values(soup: BeautifulSoup, name: str) -> list[str]:
    """Texts of a Drupal field (label excluded); several items keep page order."""

    element = _field(soup, name)
    if element is None:
        return []
    items = element.select(".field__item")
    nodes = items if items else [element]
    values: list[str] = []
    for node in nodes:
        for label in node.select(".field__label"):
            label.extract()
        text = _clean(node.get_text(" "))
        if text:
            values.append(text)
    return values


def _joined(soup: BeautifulSoup, name: str) -> str | None:
    values = _values(soup, name)
    return "; ".join(values) if values else None


def _body_text(soup: BeautifulSoup) -> str | None:
    for name in ("field-paragraphs", "field-body", "body"):
        element = _field(soup, name)
        if element is None:
            continue
        for tag in element.select("script, style"):
            tag.extract()
        for br in element.find_all("br"):
            br.replace_with("\n")
        for block in element.find_all(_BLOCK_TAGS):
            block.insert_before("\n")
            block.insert_after("\n")
        lines = [_clean(line) for line in element.get_text("").splitlines()]
        text = "\n".join(line for line in lines if line)
        if text:
            return redact_emails(text)
    return None


def parse_call_fields(html: bytes | str) -> dict[str, Any]:
    """Fields of one call from its rendered HTML (a detail page or an RSS ``description``).

    Only the fields that are not personal data are read; ``field-award-poc`` is skipped on purpose.
    """

    soup = _soup(html)
    deadline_tag = soup.select_one(".field--name-field-award-deadline time[datetime]")
    status = _values(soup, "field-award-status")
    heading = soup.select_one("h1")
    return {
        "title": _clean(heading.get_text()) if heading else None,
        "status": status[0] if status else None,
        "call_type": _joined(soup, "field-award-call-for"),
        "deadline": _to_utc(str(deadline_tag["datetime"])) if deadline_tag else None,
        "program": _joined(soup, "field-program"),
        "duration": _joined(soup, "field-award-duration"),
        "topic": _joined(soup, "field-topic"),
        "funded_by": _joined(soup, "field-award-funded-by"),
        "budget": _joined(soup, "field-award-budget"),
        "award_type": _joined(soup, "field-funding-awards-type"),
        "description_text": _body_text(soup),
    }


@dataclass(frozen=True)
class CallRecord:
    """One call: the bronze record and the findings the run logs about it."""

    record: dict[str, Any]
    findings: tuple[str, ...]


def build_record(
    *,
    slug: str,
    source_url: str,
    fields: dict[str, Any],
    extraction_path: str,
    retrieved_at: str,
    node_id: str | None = None,
    feed_published_at: str | None = None,
    listing: ListingEntry | None = None,
) -> CallRecord:
    """Assemble the flat record whose keys are the columns of the contract.

    The listing section is a cross-check of ``status``: when it disagrees with the Status field
    of the page, the page wins and the disagreement is returned as a finding (Gate H2 rule).
    Values missing from the page fall back to the listing row (title, call type, deadline).
    """

    findings: list[str] = []
    title = fields.get("title") or (listing.title if listing else None)
    if not title:
        raise IdrcParseError(f"Call {slug!r} has no title.")
    status = fields.get("status")
    if listing is not None:
        listed = "Open" if listing.section == SECTION_OPEN else "Closed"
        if status and status.strip().lower() != listed.lower():
            findings.append(
                f"status_mismatch slug={slug} listing={listed} page={status} "
                f"extraction_path={extraction_path}"
            )
        status = status or listed
    if not status:
        raise IdrcParseError(f"Call {slug!r} has no status on the page or in the listing.")
    record: dict[str, Any] = {
        "call_slug": slug,
        "source_url": source_url,
        "node_id": node_id,
        "title": title,
        "status": status,
        "call_type": fields.get("call_type") or (listing.call_type if listing else None),
        "deadline": fields.get("deadline") or (listing.deadline if listing else None),
        "program": fields.get("program"),
        "duration": fields.get("duration"),
        "topic": fields.get("topic"),
        "funded_by": fields.get("funded_by"),
        "budget": fields.get("budget"),
        "award_type": fields.get("award_type"),
        "description_text": fields.get("description_text"),
        "feed_published_at": feed_published_at,
        "extraction_path": extraction_path,
        "retrieved_at": retrieved_at,
    }
    return CallRecord(record=record, findings=tuple(findings))
