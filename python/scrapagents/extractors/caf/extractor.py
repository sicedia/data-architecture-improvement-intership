"""CAF extractor: scrape convocatorias from www.caf.com and stream to SourceRuntime."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from scrapagents.contracts.loader import load_ingestion_config
from scrapagents.runtime_client import HttpRuntimeClient, RuntimeIngestError
from scrapagents.stealth.base import ObscuraConfig

logger = logging.getLogger(__name__)

SOURCE = "caf"
DATASET = "convocatorias"
DEFAULT_USER_AGENT = "ScrapAgents-ingest-caf/0.1 (research; non-commercial)"


def run(
    router: Any,
    client: Any,
    *,
    acquisition: dict[str, Any],
    ingest_date: str,
) -> int:
    """Read CAF convocatorias, parse deterministically, and stream to Rust runtime."""
    base_url = str(acquisition.get("site", "https://www.caf.com"))
    path = str(acquisition.get("listing_path", "/es/trabaja-con-nosotros/convocatorias/"))
    target_url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    logger.info("Fetching target: %s", target_url)

    timeout = float(acquisition.get("request_timeout_seconds", 30))
    snapshot = router.fetch(target_url, timeout_seconds=timeout)
    if snapshot.blocked_by:
        logger.warning("Target blocked by %s (HTTP %s)", snapshot.blocked_by, snapshot.status)

    records: list[dict[str, Any]] = []

    # Stream JSON records to the Rust runtime (Invariant 4)
    client.ingest_json(
        source_system=SOURCE,
        dataset=DATASET,
        ingest_date=ingest_date,
        records=records,
    )
    return len(records)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point executed by Airflow task."""
    parser = argparse.ArgumentParser(prog="caf-extractor", description=__doc__)
    parser.add_argument("--dataset", default=DATASET, help=f"dataset name, defaults to {DATASET!r}")
    parser.add_argument("--ingest-date", help="YYYY-MM-DD partition date")
    parser.add_argument(
        "--runtime-url", default=os.environ.get("RUNTIME_URL", "http://127.0.0.1:8088")
    )
    args = parser.parse_args(argv)
    if args.dataset != DATASET:
        print(f"error: unsupported caf dataset {args.dataset!r}", file=sys.stderr)
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
            print(f"caf: ingested {count} records into dataset {DATASET}")
        except (RuntimeIngestError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
