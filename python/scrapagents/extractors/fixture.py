"""Fixture extractor: streams the files of a directory to the runtime, one dataset per file.

It is the reference shape of a production extractor: read bytes, stream them, keep the receipt.
It never hashes, classifies or stores anything itself (invariant 4) and contains no AI
(invariant 1).
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from scrapagents.runtime_client import (
    HttpRuntimeClient,
    LandingReceipt,
    RuntimeIngestError,
    SourceRuntimeClient,
)

CHUNK_SIZE = 64 * 1024


def read_chunks(path: Path, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


def dataset_name(path: Path) -> str:
    """File stem reduced to the runtime's name alphabet ``[a-z0-9_-]``."""
    return re.sub(r"[^a-z0-9_-]+", "_", path.stem.lower()).strip("_") or "dataset"


class FixtureExtractor:
    def __init__(self, client: SourceRuntimeClient, directory: Path, source_id: str = "fixture"):
        self._client = client
        self._directory = directory
        self._source_id = source_id

    def run(
        self, ingest_date: str | None = None, dataset: str | None = None
    ) -> dict[str, LandingReceipt]:
        """Ingest every file (or only ``dataset``); returns the receipts keyed by file name."""
        receipts: dict[str, LandingReceipt] = {}
        for path in sorted(p for p in self._directory.iterdir() if p.is_file()):
            if dataset is not None and dataset_name(path) != dataset:
                continue
            content_type, _ = mimetypes.guess_type(path.name)
            receipts[path.name] = self._client.ingest(
                self._source_id,
                dataset_name(path),
                read_chunks(path),
                content_type=content_type,
                filename=path.name,
                ingest_date=ingest_date,
            )
        return receipts


def main(argv: list[str] | None = None) -> int:
    """``python -m scrapagents.extractors.fixture``: the command an Airflow task runs."""
    parser = argparse.ArgumentParser(prog="fixture-extractor", description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    default_url = os.environ.get("RUNTIME_URL", "http://127.0.0.1:8088")
    parser.add_argument("--runtime-url", default=default_url)
    parser.add_argument("--source", default="fixture")
    parser.add_argument("--dataset", help="only the file whose dataset name matches")
    parser.add_argument("--ingest-date", help="YYYY-MM-DD partition (the DAG passes it)")
    args = parser.parse_args(argv)
    extractor = FixtureExtractor(HttpRuntimeClient(args.runtime_url), args.directory, args.source)
    try:
        receipts = extractor.run(args.ingest_date, args.dataset)
    except (RuntimeIngestError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not receipts:
        print(f"error: no file matches dataset {args.dataset!r}", file=sys.stderr)
        return 1
    for name, r in receipts.items():
        print(f"{name}: route={r.route} sha256={r.sha256} key={r.object_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
