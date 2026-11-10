"""IDRC extractor: read the site, parse deterministically, stream to the Rust runtime.

Reading order (Gate H2): the RSS feed is the primary path (each item carries the rendered page);
the HTML listing is read for completeness; the detail page only of the calls the feed does not
carry, parsed with the same field parser. A call keeps the same key (``call_slug``) whichever path
produced it.

Everything is read and parsed BEFORE anything is landed, so a block, a non-200 answer or a
structure change stops the run with nothing written. Then, through the runtime (invariant 4):

* the original bytes of every page, unmodified, as dataset ``funding_opportunities_raw`` (xml and
  html are not complex binaries: the worker lands them and never calls Tika);
* ONE JSON document ``{"records": [...]}`` as dataset ``funding_opportunities``, which the worker
  also loads into ``bronze.idrc__funding_opportunities``.

The raw bytes keep the staff email of ``dc:creator`` and ``field-award-poc``; they inherit the
30-day personal-data retention and dbt never reads them.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from scrapagents.contracts.loader import load_ingestion_config
from scrapagents.extractors.idrc.fetcher import IdrcFetchError, PoliteFetcher
from scrapagents.extractors.idrc.records import (
    CallRecord,
    IdrcParseError,
    ListingEntry,
    build_record,
    parse_call_fields,
    parse_feed,
    parse_listing,
)
from scrapagents.runtime_client import (
    HttpRuntimeClient,
    LandingReceipt,
    RuntimeIngestError,
    SourceRuntimeClient,
)
from scrapagents.stealth.base import ObscuraConfig, PageSnapshot, StealthRouter

logger = logging.getLogger(__name__)

SOURCE = "idrc"
DATASET = "funding_opportunities"
RAW_DATASET = "funding_opportunities_raw"
DEFAULT_USER_AGENT = "ScrapAgents-ingest-idrc/0.1 (research; non-commercial)"


@dataclass(frozen=True)
class RawObject:
    name: str
    content_type: str
    page: PageSnapshot


@dataclass
class CollectedCalls:
    records: list[dict[str, Any]] = field(default_factory=list)
    raw_objects: list[RawObject] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    feed_items: int = 0
    listing_calls: int = 0


@dataclass(frozen=True)
class RunResult:
    records: int
    raw_objects: int
    requests: int
    findings: tuple[str, ...]
    receipts: tuple[LandingReceipt, ...]


def collect_calls(
    fetcher: PoliteFetcher, *, acquisition: dict[str, Any], retrieved_at: str
) -> CollectedCalls:
    """Read the feed, the listing and the missing detail pages; return records and raw bytes."""

    collected = CollectedCalls()

    feed_page = fetcher.fetch(str(acquisition["rss_path"]))
    collected.raw_objects.append(RawObject("feed.xml", "application/rss+xml", feed_page))
    feed_items = parse_feed(feed_page.body)
    collected.feed_items = len(feed_items)

    listing_page = fetcher.fetch(str(acquisition["listing_path"]))
    collected.raw_objects.append(RawObject("listing.html", "text/html", listing_page))
    entries = parse_listing(listing_page.body)
    if not entries:
        raise IdrcParseError("The IDRC listing has no calls: the page structure changed.")
    collected.listing_calls = len(entries)
    by_slug: dict[str, ListingEntry] = {entry.slug: entry for entry in entries}

    calls: dict[str, CallRecord] = {}
    for item in feed_items:
        if item.slug in calls:
            collected.findings.append(f"duplicate_feed_item slug={item.slug}")
            continue
        fields = parse_call_fields(item.html)
        if item.title:
            fields["title"] = item.title
        calls[item.slug] = build_record(
            slug=item.slug,
            source_url=item.url,
            fields=fields,
            extraction_path="rss",
            retrieved_at=retrieved_at,
            node_id=item.node_id,
            feed_published_at=item.published_at,
            listing=by_slug.get(item.slug),
        )

    for entry in entries:
        if entry.slug in calls:
            continue
        detail_page = fetcher.fetch(entry.url_path)
        collected.raw_objects.append(
            RawObject(f"detail__{entry.slug}.html", "text/html", detail_page)
        )
        calls[entry.slug] = build_record(
            slug=entry.slug,
            source_url=fetcher.url(entry.url_path),
            fields=parse_call_fields(detail_page.body),
            extraction_path="html",
            retrieved_at=retrieved_at,
            listing=entry,
        )

    for slug in sorted(calls):
        collected.records.append(calls[slug].record)
        collected.findings.extend(calls[slug].findings)
    unlisted = sorted(set(calls) - set(by_slug))
    if unlisted:
        collected.findings.append(f"feed_calls_not_in_listing slugs={','.join(unlisted)}")
    if not collected.records:
        raise IdrcParseError("The IDRC source produced no records.")
    return collected


def run(
    fetcher: PoliteFetcher,
    client: SourceRuntimeClient,
    *,
    acquisition: dict[str, Any],
    ingest_date: str,
    now: datetime | None = None,
) -> RunResult:
    retrieved_at = (now or datetime.now(UTC)).replace(microsecond=0).isoformat()
    collected = collect_calls(fetcher, acquisition=acquisition, retrieved_at=retrieved_at)

    receipts: list[LandingReceipt] = []
    for raw in collected.raw_objects:
        receipts.append(
            client.ingest(
                SOURCE,
                RAW_DATASET,
                [raw.page.body],
                content_type=raw.content_type,
                filename=raw.name,
                ingest_date=ingest_date,
            )
        )
    document = json.dumps({"records": collected.records}, sort_keys=True).encode("utf-8")
    receipts.append(
        client.ingest(
            SOURCE,
            DATASET,
            [document],
            content_type="application/json",
            filename="records.json",
            ingest_date=ingest_date,
        )
    )
    for finding in collected.findings:
        logger.warning("idrc finding: %s", finding)
    return RunResult(
        records=len(collected.records),
        raw_objects=len(collected.raw_objects),
        requests=fetcher.requests_made,
        findings=tuple(collected.findings),
        receipts=tuple(receipts),
    )


def build_fetcher(
    config: dict[str, Any], router: StealthRouter, *, user_agent: str
) -> PoliteFetcher:
    acquisition = config["acquisition"]
    return PoliteFetcher(
        router,
        base_url=str(acquisition["site"]),
        user_agent=user_agent,
        min_seconds_between_requests=float(acquisition["min_seconds_between_requests"]),
        max_requests=int(acquisition["max_requests_per_run"]),
        timeout_seconds=float(acquisition.get("request_timeout_seconds", 30)),
    )


def main(argv: list[str] | None = None) -> int:
    """``python -m scrapagents.extractors.idrc``: the command an Airflow task runs."""
    parser = argparse.ArgumentParser(prog="idrc-extractor", description=__doc__)
    parser.add_argument("--dataset", default=DATASET, help=f"only {DATASET!r} is supported")
    parser.add_argument("--ingest-date", help="YYYY-MM-DD partition (the DAG passes it)")
    parser.add_argument(
        "--runtime-url", default=os.environ.get("RUNTIME_URL", "http://127.0.0.1:8088")
    )
    args = parser.parse_args(argv)
    if args.dataset != DATASET:
        print(f"error: unsupported idrc dataset {args.dataset!r}", file=sys.stderr)
        return 2

    from scrapagents.runtime_client.client import today_utc  # noqa: PLC0415
    from scrapagents.stealth.playwright_obscura import PlaywrightObscuraRouter  # noqa: PLC0415

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load_ingestion_config(SOURCE)
    obscura = ObscuraConfig.from_env()
    if obscura.cdp_url and not obscura.cdp_token:
        print(
            "error: OBSCURA_CDP_TOKEN is required: Obscura refuses CDP without it", file=sys.stderr
        )
        return 2
    user_agent = obscura.user_agent or DEFAULT_USER_AGENT
    obscura = ObscuraConfig(obscura.cdp_url, obscura.cdp_token, user_agent)
    fetcher = build_fetcher(config, PlaywrightObscuraRouter(obscura), user_agent=user_agent)
    try:
        result = run(
            fetcher,
            HttpRuntimeClient(args.runtime_url),
            acquisition=config["acquisition"],
            ingest_date=args.ingest_date or today_utc(),
        )
    except (IdrcFetchError, IdrcParseError, RuntimeIngestError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        fetcher.close()
    for r in result.receipts:
        print(f"{r.dataset}: route={r.route} sha256={r.sha256} rows={r.bronze_rows}")
    print(
        f"records={result.records} raw_objects={result.raw_objects} "
        f"requests={result.requests} findings={len(result.findings)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
