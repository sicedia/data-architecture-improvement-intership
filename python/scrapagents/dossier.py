"""Design-time dossier of one ingestion: state machine and human-gate checks.

A dossier lives in ``ingestions/<id>/`` and records the 5-phase workflow of ``AGENTS.md``
(section 3). The gates are the only place where a human decision is recorded, so the
check below refuses any state in which a phase was passed without an approved gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from scrapagents.contracts.loader import load_yaml
from scrapagents.paths import INGESTIONS_DIR, REPO_ROOT, TEMPLATE_DIR

PHASES = ("discovery", "assessment", "blueprint", "implement", "verify", "done")
# gate -> index of the first phase that requires it to be approved
GATES = {
    "h1": PHASES.index("blueprint"),
    "h2": PHASES.index("implement"),
    "pr": PHASES.index("done"),
}
GATE_STATUSES = ("pending", "approved", "rejected")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TEAMS = ("sistemas_internos", "iditi", "inteligencia_artificial", "seguridad_informacion")
SOURCE_TYPES = ("api", "database", "file", "web")
TEMPLATE_FILES = {
    "state.yml.j2": "state.yml",
    "discovery.md.j2": "discovery.md",
    "assessment.md.j2": "assessment.md",
    "blueprint.yml.j2": "blueprint.yml",
    "contract.yml.j2": "contract.yml",
}


class DossierError(RuntimeError):
    """The dossier cannot be created (bad input or it already exists)."""


@dataclass(frozen=True)
class Dossier:
    path: Path
    state: dict[str, Any]


def create_dossier(
    ingestion_id: str,
    team: str,
    *,
    dataset: str = "records",
    source_type: str = "api",
    root: Path | None = None,
    template_dir: Path | None = None,
) -> Path:
    """Render ``ingestions/_template`` into ``ingestions/<id>/`` and return its path."""

    for label, value in (("ID", ingestion_id), ("DATASET", dataset)):
        if not ID_RE.match(value):
            raise DossierError(f"{label} '{value}' must match {ID_RE.pattern}")
    if team not in TEAMS:
        raise DossierError(f"TEAM '{team}' must be one of: {', '.join(TEAMS)}")
    if source_type not in SOURCE_TYPES:
        raise DossierError(f"TYPE '{source_type}' must be one of: {', '.join(SOURCE_TYPES)}")

    target = (root or INGESTIONS_DIR) / ingestion_id
    if target.exists():
        raise DossierError(f"{target} already exists")

    env = Environment(
        loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # noqa: S701 - YAML and Markdown output, not HTML
    )
    context = {
        "ingestion_id": ingestion_id,
        "team": team,
        "dataset": dataset,
        "source_type": source_type,
    }
    target.mkdir(parents=True)
    for template_name, output_name in TEMPLATE_FILES.items():
        (target / output_name).write_text(
            env.get_template(template_name).render(**context), encoding="utf-8", newline="\n"
        )
    return target


def load_dossier(path: Path) -> Dossier:
    state = load_yaml(path / "state.yml")
    if not isinstance(state, dict):
        raise DossierError(f"{path / 'state.yml'} must be a mapping")
    return Dossier(path, state)


def check_state(state: dict[str, Any]) -> list[str]:
    """Errors of one ``state.yml``: unknown phase, bad gate, or a phase passed without its gate."""

    errors: list[str] = []
    phase = state.get("phase")
    if phase not in PHASES:
        return [f"phase '{phase}' must be one of: {', '.join(PHASES)}"]
    gates = state.get("gates")
    if not isinstance(gates, dict):
        return ["gates must be a mapping with h1, h2 and pr"]
    phase_index = PHASES.index(phase)

    for name, required_from in GATES.items():
        gate = gates.get(name)
        if not isinstance(gate, dict):
            errors.append(f"gate {name} is missing")
            continue
        status = gate.get("status")
        if status not in GATE_STATUSES:
            errors.append(
                f"gate {name}.status '{status}' must be one of: {', '.join(GATE_STATUSES)}"
            )
            continue
        approved_by = gate.get("approved_by")
        if status == "approved" and not (isinstance(approved_by, str) and approved_by.strip()):
            errors.append(f"gate {name} is approved without approved_by (a human must sign)")
        if status != "approved" and approved_by:
            errors.append(f"gate {name} has approved_by but status is '{status}'")
        if phase_index >= required_from and status != "approved":
            errors.append(
                f"phase '{phase}' requires gate {name} to be approved (status: {status})"
            )
    return errors


def check_dossiers(root: Path | None = None) -> list[str]:
    """Check every dossier under ``ingestions/`` (``_``-prefixed folders are templates)."""

    errors: list[str] = []
    base = root or INGESTIONS_DIR
    if not base.is_dir():
        return errors
    for path in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if not (path / "state.yml").is_file():
            errors.append(f"{path.name}: missing state.yml")
            continue
        try:
            dossier = load_dossier(path)
        except (DossierError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        errors.extend(f"{path.name}: {error}" for error in check_state(dossier.state))
    return errors


# Harness-only sources whose Producto OI model needs no dossier (they are not institutions).
HARNESS_SOURCES = frozenset({"fixture"})


def check_producto_oi(models_dir: Path | None = None, root: Path | None = None) -> list[str]:
    """Producto OI models of a real source exist only after its gates H1 and H2 are approved.

    Models live in ``dbt/models/producto_oi/<ingestion_id>/``. Staging and intermediate models are
    generated from contracts and are not gated; the business semantics of Producto OI are.
    """

    base = models_dir or REPO_ROOT / "dbt" / "models" / "producto_oi"
    dossiers = root or INGESTIONS_DIR
    if not base.is_dir():
        return []
    errors: list[str] = []
    for path in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if path.name in HARNESS_SOURCES:
            continue
        where = f"dbt/models/producto_oi/{path.name}"
        if not (dossiers / path.name / "state.yml").is_file():
            errors.append(f"{where}: no dossier ingestions/{path.name}/ (needs gates H1 and H2)")
            continue
        try:
            gates = load_dossier(dossiers / path.name).state.get("gates") or {}
        except (DossierError, yaml.YAMLError) as exc:
            errors.append(f"{where}: {exc}")
            continue
        for name in ("h1", "h2"):
            gate = gates.get(name) or {}
            signed = gate.get("status") == "approved" and str(gate.get("approved_by") or "").strip()
            if not signed:
                errors.append(f"{where}: gate {name} of '{path.name}' is not approved by a human")
    return errors
