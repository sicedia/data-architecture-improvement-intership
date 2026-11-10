"""Repository paths shared by the package, the scripts and the tests."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INGESTIONS_DIR = REPO_ROOT / "ingestions"
TEMPLATE_DIR = INGESTIONS_DIR / "_template"


def config_root() -> Path:
    """Root that holds ``configs/contracts`` and ``configs/ingestions`` (this repository).

    ``SCRAPAGENTS_CONFIG_ROOT`` overrides it, for example to point tests at a scratch tree.
    """

    override = os.environ.get("SCRAPAGENTS_CONFIG_ROOT")
    root = Path(override) if override else REPO_ROOT
    if not (root / "configs" / "contracts").is_dir():
        raise FileNotFoundError(f"no configs/contracts directory under {root}")
    return root
