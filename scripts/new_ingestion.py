#!/usr/bin/env python3
"""Create the design-time dossier of a new ingestion (`make new-ingestion`).

    make new-ingestion ID=world_bank TEAM=iditi [DATASET=projects] [TYPE=api]

Writes ``ingestions/<id>/`` (state, discovery, assessment, blueprint and draft contract).
The implementation files (`configs/ingestions`, `configs/contracts`, the extractor) are NOT written
here: they are created in Phase 4, after Gates H1 and H2; DAGs, bronze and dbt are generated.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from scrapagents.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["new-ingestion", *sys.argv[1:]]))
