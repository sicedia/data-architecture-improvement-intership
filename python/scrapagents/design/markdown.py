"""Tiny readers for the dossier's Markdown evidence (``- Label: value`` lines and tables)."""

from __future__ import annotations

import re

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BULLET = re.compile(r"^- ([^:\n]+):[ \t]*(.*)$")
_TODO = re.compile(r"\bTODO\b", re.IGNORECASE)


def strip_comments(text: str) -> str:
    return _COMMENT.sub("", text)


def bullets(text: str) -> dict[str, str]:
    """``label -> value`` of every ``- Label: value`` line; indented lines continue the value."""

    found: dict[str, str] = {}
    label: str | None = None
    for line in strip_comments(text).splitlines():
        match = _BULLET.match(line)
        if match:
            label = match.group(1).strip()
            found.setdefault(label, match.group(2).strip())
        elif label and line[:1] in {" ", "\t"} and line.strip():
            found[label] = f"{found[label]} {line.strip()}".strip()
        else:
            label = None
    return found


def is_filled(value: str | None) -> bool:
    return bool(value and value.strip() and not _TODO.search(value))


def lookup(found: dict[str, str], key: str) -> str | None:
    """Value of the first label starting with ``key`` (labels may carry a suffix)."""

    for label, value in found.items():
        if label.lower().startswith(key.lower()):
            return value
    return None


def table_rows(text: str, header_prefix: str) -> list[list[str]]:
    """Data rows of the table whose header line starts with ``header_prefix``."""

    lines = strip_comments(text).splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith(header_prefix.lower()):
            rows: list[list[str]] = []
            for row in lines[index + 1 :]:
                stripped = row.strip()
                if not stripped.startswith("|"):
                    break
                if set(stripped.replace("|", "").replace(":", "").replace(" ", "")) <= {"-"}:
                    continue
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if any(cells):
                    rows.append(cells)
            return rows
    return []
