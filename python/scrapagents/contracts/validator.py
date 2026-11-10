"""Validate a data contract against this project's own rules.

The rules (allowed column types, classification, purpose for personal data, owner pattern) are the
project's; they were modelled on the conventions of CEDIA's data platform, used as a reference
only. ``python/tests/test_contracts.py`` pins them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scrapagents.contracts.loader import load_yaml

ALLOWED_COLUMN_TYPES = frozenset(
    {"string", "integer", "number", "boolean", "object", "array", "json", "date", "timestamp"}
)
ALLOWED_CLASSIFICATIONS = frozenset({"public", "internal", "personal", "sensitive"})
PURPOSE_REQUIRED = frozenset({"personal", "sensitive"})
OWNER_PATTERN = re.compile(r"^data_team_[a-z][a-z0-9_]*$")
REQUIRED_FIELDS = (
    "source_system",
    "dataset",
    "description",
    "owner",
    "grain",
    "primary_key",
    "columns",
)
COLUMN_FIELDS = ("name", "type", "required", "description")


def _column_errors(columns: list[Any], personal_data: bool) -> list[str]:
    errors: list[str] = []
    for index, column in enumerate(columns, start=1):
        if not isinstance(column, dict):
            errors.append(f"columns[{index}] must be a mapping")
            continue
        for field in COLUMN_FIELDS:
            if field not in column:
                errors.append(f"columns[{index}] missing required field '{field}'")
        col_type = column.get("type")
        if isinstance(col_type, str) and col_type not in ALLOWED_COLUMN_TYPES:
            errors.append(
                f"columns[{index}].type '{col_type}' must be one of: "
                f"{', '.join(sorted(ALLOWED_COLUMN_TYPES))}"
            )
        classification = column.get("classification")
        if classification is None:
            if personal_data:
                errors.append(f"columns[{index}] missing 'classification' (personal_data: true)")
            continue
        if classification not in ALLOWED_CLASSIFICATIONS:
            errors.append(f"columns[{index}].classification '{classification}' is not allowed")
            continue
        if classification in PURPOSE_REQUIRED:
            if not personal_data:
                errors.append(
                    f"columns[{index}] is '{classification}' but personal_data is not true"
                )
            purpose = column.get("purpose")
            if not isinstance(purpose, str) or not purpose.strip():
                errors.append(f"columns[{index}] is '{classification}' and needs a 'purpose'")
    return errors


def _not_extracted_errors(
    data: dict[str, Any], columns: list[Any], personal_data: bool
) -> list[str]:
    entries = data.get("not_extracted")
    if entries is None:
        return []
    if not isinstance(entries, list):
        return ["not_extracted must be a list"]
    errors: list[str] = []
    if not personal_data:
        errors.append("not_extracted requires personal_data: true")
    extracted = {c.get("name") for c in columns if isinstance(c, dict)}
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"not_extracted[{index}] must be a mapping")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"not_extracted[{index}] missing 'name'")
            continue
        if name in extracted:
            errors.append(f"not_extracted[{index}] '{name}' is also an extracted column")
        if name in seen:
            errors.append(f"not_extracted[{index}] '{name}' is listed twice")
        seen.add(name)
        if entry.get("classification") not in PURPOSE_REQUIRED:
            errors.append(f"not_extracted[{index}].classification must be personal or sensitive")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"not_extracted[{index}] must declare a 'reason'")
    return errors


def validate_contract(data: Any, *, path: Path | None = None) -> list[str]:
    """Errors of one parsed contract (empty list when it is valid)."""

    if not isinstance(data, dict):
        return ["contract must be a mapping"]
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing required field '{field}'")

    owner = data.get("owner")
    if owner is not None and not (isinstance(owner, str) and OWNER_PATTERN.match(owner)):
        errors.append("owner must match data_team_<team_id>")

    primary_key = data.get("primary_key")
    if primary_key is not None and not isinstance(primary_key, list):
        errors.append("primary_key must be a list")
    elif isinstance(primary_key, list) and not primary_key:
        errors.append("primary_key must contain at least one column")

    columns = data.get("columns")
    personal_data = data.get("personal_data", False)
    if not isinstance(personal_data, bool):
        errors.append("personal_data must be true or false")
        personal_data = False
    if columns is not None and not isinstance(columns, list):
        errors.append("columns must be a list")
    elif isinstance(columns, list):
        errors.extend(_column_errors(columns, personal_data))
        errors.extend(_not_extracted_errors(data, columns, personal_data))

    if path is not None:
        source_system, dataset = data.get("source_system"), data.get("dataset")
        if isinstance(source_system, str) and path.parent.name != source_system:
            errors.append(f"directory '{path.parent.name}' does not match source_system")
        if isinstance(dataset, str) and path.stem != dataset:
            errors.append(f"filename should be {dataset}.yml")
    return errors


def validate_contract_file(path: Path, *, check_location: bool = True) -> list[str]:
    """Errors of a contract file, each prefixed with the file name.

    ``check_location=False`` skips the ``<source_system>/<dataset>.yml`` path rule, for
    drafts that live inside an ingestion dossier.
    """

    try:
        data = load_yaml(path)
    except Exception as exc:  # noqa: BLE001 - report any YAML error as a validation error
        return [f"{path}: invalid YAML ({exc})"]
    return [
        f"{path}: {error}"
        for error in validate_contract(data, path=path if check_location else None)
    ]
