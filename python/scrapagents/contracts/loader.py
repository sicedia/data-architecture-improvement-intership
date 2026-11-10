"""Load the contracts and ingestion declarations of this repository (``configs/``)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from scrapagents.paths import config_root


def load_yaml(path: Path) -> Any:
    """Parsed YAML of ``path`` (``None`` for an empty file)."""

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def iter_contract_files(root: Path | None = None) -> Iterator[Path]:
    """Every ``configs/contracts/<source>/<dataset>.yml``; ``_``-prefixed names are templates."""

    contracts_dir = (root or config_root()) / "configs" / "contracts"
    for path in sorted(contracts_dir.rglob("*.y*ml")):
        if any(part.startswith("_") for part in path.relative_to(contracts_dir).parts):
            continue
        yield path


def load_contract(source_system: str, dataset: str, root: Path | None = None) -> dict[str, Any]:
    """The contract of one source dataset."""

    path = (root or config_root()) / "configs" / "contracts" / source_system / f"{dataset}.yml"
    if not path.is_file():
        raise FileNotFoundError(f"no contract for {source_system}/{dataset}: {path}")
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: contract must be a mapping")
    return data


def load_ingestion_config(ingestion_id: str, root: Path | None = None) -> dict[str, Any]:
    """The declaration of a source (``configs/ingestions/<id>.yml``)."""

    path = (root or config_root()) / "configs" / "ingestions" / f"{ingestion_id}.yml"
    if not path.is_file():
        raise FileNotFoundError(f"no ingestion config for {ingestion_id}: {path}")
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: ingestion config must be a mapping")
    return data
