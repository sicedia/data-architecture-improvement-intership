"""World Bank extractor: fetch procurement notices via Obscura and stream to SourceRuntime."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from scrapagents.contracts.loader import load_ingestion_config
from scrapagents.runtime_client import HttpRuntimeClient, RuntimeIngestError, SourceRuntimeClient
from scrapagents.stealth.base import ObscuraConfig, StealthRouter

logger = logging.getLogger(__name__)

SOURCE = "world_bank"
DATASET = "opportunities"
DEFAULT_USER_AGENT = "ScrapAgents-ingest-world_bank/0.1 (research; CC-BY-4.0 attribution)"
DETAIL_BASE_URL = "https://projects.worldbank.org/en/projects-operations/procurement-detail"

CONTRACT_FIELDS = (
    "id",
    "notice_type",
    "notice_status",
    "noticedate",
    "submission_date",
    "submission_deadline_date",
    "project_id",
    "project_name",
    "project_ctry_name",
    "bid_reference_no",
    "bid_description",
    "procurement_group",
    "procurement_method_code",
    "procurement_method_name",
    "notice_lang_name",
    "contact_organization",
    "contact_email",
    "notice_text",
)


def parse_notices(raw_body: bytes) -> list[dict[str, Any]]:
    """Deterministically normalize World Bank procnotices JSON into contracted records."""
    payload = json.loads(raw_body.decode("utf-8"))
    raw_notices = payload.get("procnotices") or []
    items = raw_notices.values() if isinstance(raw_notices, dict) else raw_notices
    records: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        notice_id = str(item.get("id") or "").strip()
        if not notice_id:
            continue
        record: dict[str, Any] = {field: item.get(field) for field in CONTRACT_FIELDS}
        record["id"] = notice_id
        record["notice_type"] = str(item.get("notice_type") or "Procurement Notice")
        record["source_url"] = f"{DETAIL_BASE_URL}/{notice_id}"
        records.append(record)
    return records


def run(
    router: StealthRouter,
    client: SourceRuntimeClient,
    *,
    acquisition: dict[str, Any],
    ingest_date: str,
) -> int:
    """Read World Bank procurement notices via StealthRouter and stream to Rust runtime."""
    api_url = str(
        acquisition.get(
            "api_url",
            "https://search.worldbank.org/api/v2/procnotices?format=json&apilang=en&rows=100&os=0",
        )
    )
    logger.info("Fetching World Bank procurement notices: %s", api_url)

    timeout = float(acquisition.get("request_timeout_seconds", 30))
    snapshot = router.fetch(api_url, timeout_seconds=timeout)
    if snapshot.blocked_by:
        raise RuntimeError(
            f"Target blocked by {snapshot.blocked_by} (HTTP {snapshot.status}); the run stops."
        )
    if snapshot.status != 200:
        raise RuntimeError(f"{api_url} answered {snapshot.status}.")

    records = parse_notices(snapshot.body)
    document = json.dumps({"records": records}, sort_keys=True).encode("utf-8")
    client.ingest(
        SOURCE,
        DATASET,
        [document],
        content_type="application/json",
        filename="opportunities.json",
        ingest_date=ingest_date,
    )
    return len(records)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point executed by Airflow task."""
    parser = argparse.ArgumentParser(prog="world_bank-extractor", description=__doc__)
    parser.add_argument("--dataset", default=DATASET, help=f"dataset name, defaults to {DATASET!r}")
    parser.add_argument("--ingest-date", help="YYYY-MM-DD partition date")
    parser.add_argument(
        "--runtime-url", default=os.environ.get("RUNTIME_URL", "http://127.0.0.1:8088")
    )
    args = parser.parse_args(argv)
    if args.dataset != DATASET:
        print(f"error: unsupported world_bank dataset {args.dataset!r}", file=sys.stderr)
        return 2

    from scrapagents.runtime_client.client import today_utc
    from scrapagents.stealth.playwright_obscura import PlaywrightObscuraRouter

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load_ingestion_config(SOURCE)
    obscura = ObscuraConfig.from_env()
    user_agent = obscura.user_agent or DEFAULT_USER_AGENT
    obscura = ObscuraConfig(obscura.cdp_url, obscura.cdp_token, user_agent)

    with PlaywrightObscuraRouter(obscura) as router:
        try:
            runtime_client = HttpRuntimeClient(args.runtime_url)
            count = run(
                router,
                runtime_client,
                acquisition=config.get("acquisition", {}),
                ingest_date=args.ingest_date or today_utc(),
            )
            print(f"world_bank: ingested {count} records into dataset {DATASET}")
        except (RuntimeIngestError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
