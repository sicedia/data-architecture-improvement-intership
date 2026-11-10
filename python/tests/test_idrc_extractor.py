"""IDRC extractor: collect the calls, stream raw bytes and one JSON document to the runtime."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scrapagents.contracts.loader import load_ingestion_config
from scrapagents.extractors.idrc.extractor import (
    DATASET,
    RAW_DATASET,
    collect_calls,
    run,
)
from scrapagents.extractors.idrc.fetcher import IdrcBlockedError, PoliteFetcher
from scrapagents.extractors.idrc.records import IdrcParseError
from scrapagents.runtime_client import InMemoryRuntimeClient
from scrapagents.stealth.base import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures" / "idrc"
BASE = "https://idrc-crdi.ca"
UA = "ScrapAgents-ingest-idrc/0.1 (research; non-commercial)"
JOHN = "idrc-invites-applications-john-g-bene-fellowship-2026"
INDIGENOUS = "connecting-indigenous-research-leadership-canada-and-global-south"
HUB = "womens-voice-and-leadership-learning-partnership-global-learning-hub"
ACQUISITION: dict[str, Any] = {"rss_path": "/en/funding/rss.xml", "listing_path": "/en/funding"}
NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
Site = dict[str, bytes | tuple[int, bytes]]


class FakeRouter:
    def __init__(self, files: Site) -> None:
        self.files = files
        self.requested: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: float = 30.0) -> PageSnapshot:
        self.requested.append(url)
        value = self.files[url.removeprefix(BASE)]
        status, body = value if isinstance(value, tuple) else (200, value)
        return PageSnapshot(url, status, None, body.decode("utf-8", "replace"), None, body)

    def close(self) -> None:
        pass


def _site(**overrides: bytes | tuple[int, bytes]) -> Site:
    site: Site = {
        "/robots.txt": b"User-agent: *\ncrawl-delay: 5\nDisallow: /search/\n",
        "/en/funding/rss.xml": (FIXTURES / "feed.xml").read_bytes(),
        "/en/funding": (FIXTURES / "listing.html").read_bytes(),
        f"/en/funding/{HUB}": (FIXTURES / "detail_listing_only.html").read_bytes(),
    }
    site.update(overrides)
    return site


def _fetcher(site: Site, *, max_requests: int = 30) -> tuple[PoliteFetcher, FakeRouter]:
    router = FakeRouter(site)
    fetcher = PoliteFetcher(
        router,
        base_url=BASE,
        user_agent=UA,
        min_seconds_between_requests=0.0,
        max_requests=max_requests,
        sleep=lambda _seconds: None,
    )
    return fetcher, router


def test_collect_reads_the_feed_first_and_the_detail_page_only_of_missing_calls() -> None:
    fetcher, router = _fetcher(_site())
    collected = collect_calls(fetcher, acquisition=ACQUISITION, retrieved_at=NOW.isoformat())
    assert [r["call_slug"] for r in collected.records] == sorted([JOHN, INDIGENOUS, HUB])
    by_slug = {r["call_slug"]: r for r in collected.records}
    assert by_slug[JOHN]["extraction_path"] == "rss"
    assert by_slug[JOHN]["node_id"] == "147196"
    assert by_slug[HUB]["extraction_path"] == "html"
    assert by_slug[HUB]["node_id"] is None
    assert by_slug[HUB]["feed_published_at"] is None
    assert router.requested == [
        f"{BASE}/robots.txt",
        f"{BASE}/en/funding/rss.xml",
        f"{BASE}/en/funding",
        f"{BASE}/en/funding/{HUB}",
    ]
    assert [raw.name for raw in collected.raw_objects] == [
        "feed.xml",
        "listing.html",
        f"detail__{HUB}.html",
    ]
    assert (collected.feed_items, collected.listing_calls, collected.findings) == (2, 3, [])


def test_a_call_in_the_feed_but_not_in_the_listing_is_kept_and_reported() -> None:
    listing = (FIXTURES / "listing.html").read_text().replace(INDIGENOUS, "something-else")
    detail = (FIXTURES / "detail_listing_only.html").read_bytes()
    site = _site(**{"/en/funding": listing.encode(), "/en/funding/something-else": detail})
    fetcher, _ = _fetcher(site)
    collected = collect_calls(fetcher, acquisition=ACQUISITION, retrieved_at=NOW.isoformat())
    assert INDIGENOUS in {r["call_slug"] for r in collected.records}
    assert any(
        f.startswith("feed_calls_not_in_listing") and INDIGENOUS in f for f in collected.findings
    )


def test_empty_listing_is_a_structure_change() -> None:
    fetcher, _ = _fetcher(_site(**{"/en/funding": b"<html><h2>Open calls</h2></html>"}))
    with pytest.raises(IdrcParseError, match="no calls"):
        collect_calls(fetcher, acquisition=ACQUISITION, retrieved_at=NOW.isoformat())


def test_a_block_stops_the_run_before_anything_is_landed() -> None:
    client = InMemoryRuntimeClient()
    fetcher, _ = _fetcher(_site(**{"/en/funding": (403, b"403 Forbidden")}))
    with pytest.raises(IdrcBlockedError):
        run(fetcher, client, acquisition=ACQUISITION, ingest_date="2026-11-09", now=NOW)
    assert client.objects == {}


def test_run_lands_the_raw_bytes_untouched_and_one_json_document() -> None:
    client = InMemoryRuntimeClient()
    fetcher, _ = _fetcher(_site())
    result = run(fetcher, client, acquisition=ACQUISITION, ingest_date="2026-11-09", now=NOW)

    assert (result.records, result.raw_objects, result.requests) == (3, 3, 4)
    datasets = [r.dataset for r in result.receipts]
    assert datasets == [RAW_DATASET, RAW_DATASET, RAW_DATASET, DATASET]  # JSON last
    assert all(key.startswith("source=idrc/") and "dt=2026-11-09" in key for key in client.objects)

    stored = list(client.objects.values())
    assert (FIXTURES / "feed.xml").read_bytes() in stored  # the staff emails are still there
    document = json.loads(client.objects[result.receipts[-1].object_key])
    assert len(document["records"]) == 3
    assert all("@" not in json.dumps(record) for record in document["records"])


def test_every_record_has_exactly_the_contract_columns() -> None:
    fetcher, _ = _fetcher(_site())
    collected = collect_calls(fetcher, acquisition=ACQUISITION, retrieved_at=NOW.isoformat())
    from scrapagents.contracts.loader import load_contract

    columns = {c["name"] for c in load_contract("idrc", DATASET)["columns"]}
    assert all(set(record) == columns for record in collected.records)


def test_the_declared_acquisition_matches_the_robots_txt_crawl_delay() -> None:
    config = load_ingestion_config("idrc")
    assert config["acquisition"]["min_seconds_between_requests"] >= 5
    assert config["airflow"]["schedule"] is None
    assert config["datasets"][DATASET]["persistence"]["max_delete_percentage"] == 15
    assert config["runtime"]["triage"]["binary_to_tika"] == ["pdf"]
