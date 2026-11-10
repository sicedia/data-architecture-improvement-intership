"""Helpers that play the agents (writing evidence) in the F5 tests."""

from __future__ import annotations

import re
from pathlib import Path

from scrapagents.design.probes import ProbeRow, append_rows
from scrapagents.dossier import create_dossier
from scrapagents.stealth.base import PageSnapshot

TODAY = "2026-11-09"


def answer(path: Path, label: str, value: str) -> None:
    """Fill the `- Label:` line that starts with ``label``."""
    text = path.read_text(encoding="utf-8")
    pattern = rf"^(- {re.escape(label)}[^:\n]*:)[ \t]*$"
    new, count = re.subn(pattern, lambda m: f"{m.group(1)} {value}", text, flags=re.M)
    assert count == 1, f"{label!r}: {count} matches in {path.name}"
    path.write_text(new, encoding="utf-8")


def add_table_row(path: Path, header_prefix: str, cells: list[str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith(header_prefix))
    end = header + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    lines.insert(end, "| " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def new_dossier(root: Path, ingestion_id: str = "acme_grants", **kwargs) -> Path:
    kwargs.setdefault("team", "iditi")
    return create_dossier(ingestion_id, root=root, **kwargs)


def fill_discovery(dossier: Path, *, status: str = "200") -> None:
    path = dossier / "discovery.md"
    answer(path, "Institution / portal URL", "https://grants.acme.example")
    answer(path, "Access type", "public API")
    answer(path, "robots.txt and Terms of Service", "allowed, read 2026-11-09 (link in notes)")
    answer(path, "Endpoints or DOM entry points", "GET /api/v1/grants")
    answer(path, "Pagination and ordering", "page and size query parameters")
    answer(path, "Authentication", "none")
    answer(path, "Payload formats", "JSON")
    answer(path, "Estimated volume and change rate", "2,000 records, weekly")
    row = ProbeRow(
        TODAY, "https://grants.acme.example/api/v1/grants", status, "application/json", "none"
    )
    append_rows(path, [row])


def fill_assessment(
    dossier: Path, *, decision: str = "go", personal: str = "no", extra_rows=()
) -> None:
    path = dossier / "assessment.md"
    answer(path, "Legal / ToS risk", "low: public data, ToS allow reuse")
    answer(path, "Anti-bot risk and mitigation", "none seen; Pool of 1 slot")
    answer(path, "Personal data", f"{personal}, none of the fields identify a person")
    answer(path, "Duplicates an existing CEDIA source", "no, checked configs/ingestions")
    answer(path, "Full scope per run or incremental", "full scope per run")
    answer(path, "Proposed schedule and why", "weekly: the source changes weekly")
    answer(path, "Decision", decision)
    answer(path, "Reason", "open data with a stable API")
    add_table_row(path, "| Payload", ["Grants search response", "json", "no"])
    for row in extra_rows:
        add_table_row(path, "| Payload", list(row))


def fill_blueprint(dossier: Path, *, description: str = "Open grants of ACME.") -> None:
    blueprint = dossier / "blueprint.yml"
    text = blueprint.read_text(encoding="utf-8").replace("TODO one sentence", description)
    blueprint.write_text(text, encoding="utf-8")
    contract = dossier / "contract.yml"
    text = contract.read_text(encoding="utf-8")
    text = text.replace("TODO what this dataset delivers.", "Open grants published by ACME.")
    text = text.replace("TODO one row per ...", "one row per grant")
    contract.write_text(text, encoding="utf-8")


def flat(dossier: Path) -> Path:
    return dossier


class FakeRouter:
    """A StealthRouter double: answers from a dict, can raise, records what was fetched."""

    def __init__(self, pages: dict[str, PageSnapshot | Exception] | None = None) -> None:
        self.pages = pages or {}
        self.fetched: list[str] = []
        self.closed = False

    def fetch(self, url: str, *, timeout_seconds: float = 30.0) -> PageSnapshot:
        self.fetched.append(url)
        page = self.pages.get(url, PageSnapshot(url, 200, "text/html; charset=utf-8", "<html/>"))
        if isinstance(page, Exception):
            raise page
        return page

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeRouter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
