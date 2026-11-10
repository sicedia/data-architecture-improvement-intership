"""Mechanical part of the architecture review (``arch-reviewer``), written to ``review.md``.

It checks the blueprint against the invariants and the sources already declared here, and
records a digest of what it looked at, so Gate H2 can only be signed on a review of the exact
blueprint a human is approving.
The ``arch-reviewer`` agent adds its judgement under ``## Reviewer notes``; that part is kept when
the report is regenerated.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scrapagents.contracts.loader import load_yaml
from scrapagents.design import blueprint as bp
from scrapagents.design.blueprint import Findings
from scrapagents.design.markdown import bullets, lookup
from scrapagents.dossier import check_state, load_dossier
from scrapagents.invariants import LLM_MODULES, imported_modules, is_llm_module
from scrapagents.paths import config_root

NOTES_MARKER = "## Reviewer notes"
DIGEST = re.compile(r"<!-- digest: ([0-9a-f]{64}) -->")
_PARTY_HINT = re.compile(
    r"(person|people|author|researcher|investigador|institution|organi[sz]ation|company|empresa"
    r"|ruc|cedula|collaborator|colaborador)",
    re.IGNORECASE,
)


def digest(dossier_dir: Path) -> str:
    """SHA-256 over everything the review depends on."""

    sha = hashlib.sha256()
    files = [dossier_dir / "assessment.md", bp.blueprint_path(dossier_dir)]
    try:
        contracts = bp.contract_files(dossier_dir, bp.load_blueprint(dossier_dir))
        files.extend(sorted(contracts.values()))
    except Exception:  # noqa: BLE001 - a broken blueprint is reported by check_blueprint
        pass
    for path in files:
        if path.is_file():
            sha.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return sha.hexdigest()


def _catalog_findings(dossier_dir: Path) -> Findings:
    """Duplicates against the sources this project already declares in ``configs/``."""

    findings = Findings()
    ingestion_id = dossier_dir.name
    try:
        root = config_root()
    except FileNotFoundError:
        return findings
    phase = str(load_dossier(dossier_dir).state.get("phase"))
    declared = (root / "configs" / "ingestions" / f"{ingestion_id}.yml").is_file()
    if declared and phase in ("discovery", "assessment", "blueprint"):
        findings.errors.append(
            f"configs/ingestions already declares {ingestion_id!r}: a second acquisition path "
            "for a source this project already has"
        )
    if (root / "configs" / "contracts" / ingestion_id).is_dir() and phase in (
        "discovery",
        "assessment",
        "blueprint",
    ):
        findings.errors.append(
            f"configs/contracts already has contracts for source_system {ingestion_id!r}"
        )
    discovery = dossier_dir / "discovery.md"
    if discovery.is_file():
        found = bullets(discovery.read_text(encoding="utf-8"))
        words = (lookup(found, "Institution / portal URL") or "").split()
        host = urlsplit(words[0]).hostname if words else None
        if host:
            for config in sorted((root / "configs" / "ingestions").glob("*.yml")):
                if (
                    config.stem != ingestion_id
                    and host in config.read_text(encoding="utf-8").lower()
                ):
                    findings.warnings.append(
                        f"configs/ingestions/{config.name} mentions {host}: confirm this is not a "
                        "second acquisition path for the same source"
                    )
    return findings


def _personal_data_findings(dossier_dir: Path, blueprint: dict[str, Any]) -> Findings:
    findings = Findings()
    declared = False
    for path in bp.contract_files(dossier_dir, blueprint).values():
        data = load_yaml(path)
        if not isinstance(data, dict):
            continue
        declared = declared or data.get("personal_data") is True
        for column in data.get("columns") or []:
            name = str(column.get("name", "")) if isinstance(column, dict) else ""
            if _PARTY_HINT.search(name):
                findings.warnings.append(
                    f"{path.name}: column {name!r} looks like a person or organization: apply "
                    "the Party decision of the pre-implementation gate (reuse, LINK or local)"
                )
    assessment = dossier_dir / "assessment.md"
    if assessment.is_file():
        found = bullets(assessment.read_text(encoding="utf-8"))
        answer = (lookup(found, "Personal data") or "").lower()
        if answer.startswith("yes") and not declared:
            findings.errors.append(
                "the assessment says personal data, but no contract has personal_data: true"
            )
        if answer.startswith("no") and declared:
            findings.errors.append("a contract has personal_data: true, but the assessment says no")
    return findings


def _code_findings(dossier_dir: Path) -> Findings:
    """Invariants 1 and 3 for any Python a dossier carries (probes, extractor drafts)."""

    findings = Findings()
    for path in sorted(dossier_dir.rglob("*.py")):
        try:
            modules = imported_modules(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            findings.errors.append(f"{path.name}: does not parse ({exc.msg})")
            continue
        for module in sorted(modules):
            if is_llm_module(module):
                findings.errors.append(
                    f"{path.name}: imports {module} (invariant 1: zero AI at run-time)"
                )
            if module == "playwright" or module.startswith("playwright."):
                findings.errors.append(
                    f"{path.name}: imports playwright directly; use scrapagents.stealth "
                    "(invariant 3)"
                )
    return findings


def _extractor_findings(blueprint: dict[str, Any]) -> Findings:
    findings = Findings()
    extractor = (blueprint.get("runtime") or {}).get("extractor") or {}
    command = str(extractor.get("command") or "").lower()
    for module in sorted(LLM_MODULES):
        if re.search(rf"(?<![\w.]){re.escape(module)}(?![\w])", command):
            findings.errors.append(f"runtime.extractor.command mentions {module} (invariant 1)")
    return findings


def review(dossier_dir: Path) -> Findings:
    """All mechanical findings for the dossier."""

    findings = bp.check_blueprint(dossier_dir)
    state = load_dossier(dossier_dir).state
    findings.errors.extend(f"state.yml: {e}" for e in check_state(state))
    try:
        blueprint = bp.load_blueprint(dossier_dir)
    except Exception:  # noqa: BLE001 - already reported by check_blueprint
        return findings
    for part in (
        _catalog_findings(dossier_dir),
        _personal_data_findings(dossier_dir, blueprint),
        _code_findings(dossier_dir),
        _extractor_findings(blueprint),
    ):
        findings.extend(part)
    return findings


def render(dossier_dir: Path, findings: Findings) -> str:
    previous = dossier_dir / "review.md"
    notes = "(arch-reviewer: judgement on ownership, shared source vs product, Party, refresh)"
    if previous.is_file():
        text = previous.read_text(encoding="utf-8")
        if NOTES_MARKER in text:
            notes = text.split(NOTES_MARKER, 1)[1].strip("\n")
    lines = [
        f"# Architecture review: {dossier_dir.name}",
        f"<!-- digest: {digest(dossier_dir)} -->",
        "Generated by `scrapagents review`; only the reviewer notes below are written by hand.",
        "",
        f"Result: {'fail' if findings.errors else 'pass'}",
        "",
        "## Errors",
        *([f"- {e}" for e in findings.errors] or ["- none"]),
        "",
        "## Warnings",
        *([f"- {w}" for w in findings.warnings] or ["- none"]),
        "",
        NOTES_MARKER,
        notes,
        "",
    ]
    return "\n".join(lines)


def write_review(dossier_dir: Path) -> Findings:
    findings = review(dossier_dir)
    text = render(dossier_dir, findings)
    (dossier_dir / "review.md").write_text(text, encoding="utf-8", newline="\n")
    return findings


def review_is_current(dossier_dir: Path) -> bool:
    """``review.md`` exists, passed, and was written for the current blueprint and contracts."""

    path = dossier_dir / "review.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    match = DIGEST.search(text)
    return bool(match and match.group(1) == digest(dossier_dir) and "\nResult: pass\n" in text)
