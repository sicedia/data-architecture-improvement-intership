"""Moving a dossier through the phases, and recording human signatures.

* ``advance`` is safe for an agent to run: it moves ``phase`` forward only when the evidence of the
  current phase is complete and the gate that closes it was signed by a human.
* ``sign`` records a human decision in ``state.yml``. It is the only code that writes
  ``approved_by``; the CLI refuses it unless it runs in an interactive terminal of a person.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from scrapagents.contracts import validate_contract_file
from scrapagents.design import evidence, review
from scrapagents.dossier import GATES, PHASES, check_state, load_dossier
from scrapagents.paths import REPO_ROOT, config_root

# Names that identify an agent, not a person: a gate is signed by a human.
_AGENT_NAMES = re.compile(r"(claude|cursor|gpt|copilot|assistant|agent|bot\b|llm|codex)", re.I)
# Phase that must be current for each gate to be signed.
SIGN_PHASE = {"h1": "assessment", "h2": "blueprint", "pr": "verify"}
# phase -> (next phase, gate that must be signed first or None)
TRANSITIONS = {
    "discovery": ("assessment", None),
    "assessment": ("blueprint", "h1"),
    "blueprint": ("implement", "h2"),
    "implement": ("verify", None),
    "verify": ("done", "pr"),
}


class WorkflowError(RuntimeError):
    """The requested move is not allowed; the message says what is missing."""


@dataclass
class Status:
    ingestion_id: str
    phase: str
    gates: dict[str, str]
    blockers: list[str] = field(default_factory=list)
    waiting_for_human: str | None = None
    next_phase: str | None = None
    note: str | None = None

    @property
    def can_advance(self) -> bool:
        return self.next_phase is not None and not self.blockers and self.waiting_for_human is None


def _read(dossier_dir: Path, name: str) -> str:
    path = dossier_dir / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def evidence_blockers(dossier_dir: Path, phase: str) -> list[str]:
    """What is missing from the evidence of ``phase`` (empty when it can be reviewed)."""

    if phase == "discovery":
        return evidence.discovery_issues(_read(dossier_dir, "discovery.md"))
    if phase == "assessment":
        text = _read(dossier_dir, "assessment.md")
        blockers = evidence.assessment_issues(text)
        if evidence.decision(text) == "no-go":
            blockers.append("assessment.md: the decision is no-go, so there is nothing to sign")
        return blockers
    if phase == "implement":
        return implementation_blockers(dossier_dir.name)
    if phase == "blueprint":
        findings = review.review(dossier_dir)
        blockers = list(findings.errors)
        if not blockers and not review.review_is_current(dossier_dir):
            blockers.append("review.md is missing or stale: run `make review ID=<id>`")
        return blockers
    return []


def implementation_blockers(ingestion_id: str) -> list[str]:
    """What the implementation of an approved blueprint still lacks in this repository."""

    root = config_root()
    blockers: list[str] = []
    if not (root / "configs" / "ingestions" / f"{ingestion_id}.yml").is_file():
        blockers.append(f"configs/ingestions/{ingestion_id}.yml is missing")
    contracts = sorted((root / "configs" / "contracts" / ingestion_id).glob("*.yml"))
    if not contracts:
        blockers.append(f"configs/contracts/{ingestion_id}/ has no contract")
    for path in contracts:
        blockers.extend(validate_contract_file(path))
    extractor = REPO_ROOT / "python" / "scrapagents" / "extractors" / ingestion_id
    if not (extractor / "__init__.py").is_file():
        blockers.append(f"python/scrapagents/extractors/{ingestion_id}/ is missing")
    return blockers


def _signed(state: dict, gate: str) -> bool:
    entry = (state.get("gates") or {}).get(gate) or {}
    return entry.get("status") == "approved" and bool(str(entry.get("approved_by") or "").strip())


def status(dossier_dir: Path) -> Status:
    state = load_dossier(dossier_dir).state
    phase = str(state.get("phase"))
    gates = {g: str(((state.get("gates") or {}).get(g) or {}).get("status")) for g in GATES}
    result = Status(dossier_dir.name, phase, gates)
    result.blockers.extend(check_state(state))
    if phase not in TRANSITIONS:
        result.note = "nothing to advance: the dossier is done" if phase in PHASES else None
        return result
    result.next_phase, gate = TRANSITIONS[phase]
    result.blockers.extend(evidence_blockers(dossier_dir, phase))
    if gate and not _signed(state, gate) and not result.blockers:
        result.waiting_for_human = (
            f"gate {gate.upper()}: a human must run `make sign ID={dossier_dir.name} "
            f'GATE={gate} BY="<name>"`'
        )
    return result


def advance(dossier_dir: Path) -> str:
    """Move to the next phase when the evidence is complete and the gate is signed."""

    current = status(dossier_dir)
    if current.next_phase is None:
        raise WorkflowError(current.note or f"nothing to advance from phase {current.phase!r}")
    problems = list(current.blockers)
    if current.waiting_for_human:
        problems.append(current.waiting_for_human)
    if problems:
        raise WorkflowError("; ".join(problems))
    _write_state(dossier_dir, lambda text: _set_phase(text, current.next_phase))
    return current.next_phase


def _set_phase(text: str, phase: str) -> str:
    new, count = re.subn(r"^phase: \w+[ \t]*$", f"phase: {phase}", text, count=1, flags=re.M)
    if count != 1:
        raise WorkflowError("state.yml has no 'phase:' line to update")
    return new


def _set_gate(text: str, gate: str, by: str, today: str) -> str:
    pattern = (
        rf"(^  {gate}:\n    status: )\w+(\n    approved_by: )[^\n]*(\n    approved_at: )[^\n]*"
    )
    new, count = re.subn(
        pattern,
        lambda m: (
            f"{m.group(1)}approved{m.group(2)}{json.dumps(by)}{m.group(3)}{json.dumps(today)}"
        ),
        text,
        count=1,
        flags=re.M,
    )
    if count != 1:
        raise WorkflowError(f"state.yml has no standard block for gate {gate}")
    return new


def _write_state(dossier_dir: Path, change) -> None:
    path = dossier_dir / "state.yml"
    new = change(path.read_text(encoding="utf-8"))
    errors = check_state(yaml.safe_load(new))
    if errors:
        raise WorkflowError("the change would leave state.yml invalid: " + "; ".join(errors))
    path.write_text(new, encoding="utf-8", newline="\n")


def sign(dossier_dir: Path, gate: str, by: str, *, today: str | None = None) -> None:
    """Record the human approval of ``gate``; the caller must have authenticated a person."""

    if gate not in SIGN_PHASE:
        raise WorkflowError(f"gate must be one of: {', '.join(SIGN_PHASE)}")
    if not by.strip() or _AGENT_NAMES.search(by):
        raise WorkflowError("a gate is signed by a person: give your own name")
    state = load_dossier(dossier_dir).state
    if state.get("phase") != SIGN_PHASE[gate]:
        raise WorkflowError(
            f"gate {gate} is signed in phase {SIGN_PHASE[gate]!r}, not {state.get('phase')!r}"
        )
    if _signed(state, gate):
        raise WorkflowError(f"gate {gate} is already signed")
    if gate != "pr":
        blockers = evidence_blockers(dossier_dir, SIGN_PHASE[gate])
        if blockers:
            raise WorkflowError("the evidence is incomplete: " + "; ".join(blockers))
    stamp = today or datetime.date.today().isoformat()
    _write_state(dossier_dir, lambda text: _set_gate(text, gate, by.strip(), stamp))
