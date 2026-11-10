"""Checks of ``blueprint.yml`` and its draft contracts, the evidence for Gate H2.

Everything here is mechanical: it proves the blueprint is complete and that the artifacts the
platform generates from it (typed bronze, dbt models, the DAG) can be generated. Whether the design
is *good* is the job of the human and of ``arch-reviewer``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scrapagents.bronze.generator import BronzeGenerationError
from scrapagents.bronze.generator import build_files as build_bronze
from scrapagents.contracts import validate_contract_file
from scrapagents.contracts.loader import load_yaml
from scrapagents.dags.generator import DagGenerationError, build_dag
from scrapagents.dbt.generator import Contract, DbtGenerationError, contract_from_file
from scrapagents.dbt.generator import build_files as build_dbt
from scrapagents.design import evidence
from scrapagents.design.markdown import is_filled
from scrapagents.dossier import SOURCE_TYPES, TEAMS, load_dossier
from scrapagents.invariants import TIKA_FORMATS

LANDING_FORMATS = frozenset({"json"})


@dataclass
class Findings:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def extend(self, other: Findings) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


def blueprint_path(dossier_dir: Path) -> Path:
    return dossier_dir / "blueprint.yml"


def load_blueprint(dossier_dir: Path) -> dict[str, Any]:
    data = load_yaml(blueprint_path(dossier_dir))
    if not isinstance(data, dict):
        raise ValueError("blueprint.yml must be a mapping")
    return data


def contract_files(dossier_dir: Path, blueprint: dict[str, Any]) -> dict[str, Path]:
    """Dataset -> draft contract path, only for paths that stay inside the dossier."""

    found: dict[str, Path] = {}
    root = dossier_dir.resolve()
    for name, dataset in (blueprint.get("datasets") or {}).items():
        ref = (dataset or {}).get("contract") if isinstance(dataset, dict) else None
        if not isinstance(ref, str):
            continue
        path = (dossier_dir / ref).resolve()
        if path.is_relative_to(root) and path.is_file():
            found[name] = path
    return found


def _identity(blueprint: dict[str, Any], dossier_dir: Path) -> list[str]:
    errors: list[str] = []
    ingestion_id = dossier_dir.name
    state = load_dossier(dossier_dir).state
    if blueprint.get("ingestion_id") != ingestion_id:
        errors.append(f"ingestion_id must be {ingestion_id!r}")
    if blueprint.get("source_system") != ingestion_id:
        errors.append(f"source_system must be {ingestion_id!r} (naming convention)")
    if blueprint.get("source_type") not in SOURCE_TYPES:
        errors.append(f"source_type must be one of {', '.join(SOURCE_TYPES)}")
    elif blueprint.get("source_type") != state.get("source_type"):
        errors.append("source_type differs from state.yml")
    team = blueprint.get("owning_team")
    if team not in TEAMS:
        errors.append(f"owning_team must be one of {', '.join(TEAMS)}")
    elif team != state.get("owning_team"):
        errors.append("owning_team differs from state.yml")
    if blueprint.get("owner") != f"data_team_{team}":
        errors.append(f"owner must be data_team_{team}")
    for key in ("display_name", "description"):
        if not is_filled(str(blueprint.get(key) or "")):
            errors.append(f"{key} is missing or still a TODO")
    return errors


def _dataset_errors(ingestion_id: str, name: str, dataset: Any, contract: Path | None) -> list[str]:
    if not isinstance(dataset, dict):
        return [f"datasets.{name} must be a mapping"]
    errors: list[str] = []
    if contract is None:
        errors.append(f"datasets.{name}.contract must name a contract file inside the dossier")
    else:
        errors.extend(validate_contract_file(contract, check_location=False))
        data = load_yaml(contract)
        if isinstance(data, dict):
            if data.get("source_system") != ingestion_id:
                errors.append(f"{contract.name}: source_system must be {ingestion_id!r}")
            if data.get("dataset") != name:
                errors.append(f"{contract.name}: dataset must be {name!r}")
            for key in ("description", "grain"):
                if not is_filled(str(data.get(key) or "")):
                    errors.append(f"{contract.name}: {key} is still a TODO")
            persistence = (dataset.get("persistence") or {}).get("key")
            if persistence is not None and persistence != data.get("primary_key"):
                errors.append(
                    f"datasets.{name}.persistence.key must equal the contract primary_key"
                )
    expected = f"{ingestion_id}__{name}"
    if dataset.get("bronze_table") not in (None, expected):
        errors.append(f"datasets.{name}.bronze_table must be {expected!r}")
    landing = dataset.get("landing_format", "json")
    if landing not in LANDING_FORMATS:
        errors.append(
            f"datasets.{name}.landing_format {landing!r}: "
            f"the RustWorker loads {sorted(LANDING_FORMATS)}"
        )
    return errors


def _platform_errors(blueprint: dict[str, Any], ingestion_id: str) -> list[str]:
    errors: list[str] = []
    airflow = blueprint.get("airflow") or {}
    if "schedule" not in airflow:
        errors.append("airflow.schedule must be declared (null for on demand)")
    if not isinstance(airflow.get("pool"), str):
        errors.append("airflow.pool is required: one Pool per site rate-limits the requests")
    selector = (blueprint.get("dbt") or {}).get("selector")
    if selector != f"tag:source_{ingestion_id}":
        errors.append(f"dbt.selector must be 'tag:source_{ingestion_id}'")
    runtime = blueprint.get("runtime") or {}
    binaries = (runtime.get("triage") or {}).get("binary_to_tika", [])
    if not isinstance(binaries, list) or not set(binaries) <= TIKA_FORMATS:
        errors.append(
            f"runtime.triage.binary_to_tika may only list {sorted(TIKA_FORMATS)} (invariant 4)"
        )
    if blueprint.get("source_type") == "web" and not (runtime.get("extractor") or {}).get(
        "stealth"
    ):
        errors.append(
            "a web source needs runtime.extractor.stealth: true (playwright + obscura.sh)"
        )
    return errors


def _generation_errors(
    blueprint: dict[str, Any], ingestion_id: str, contracts: dict[str, Path]
) -> list[str]:
    """Dry run of what the platform generates from this blueprint."""

    errors: list[str] = []
    try:
        build_dag(blueprint, f"ingestions/{ingestion_id}/blueprint.yml")
    except (DagGenerationError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"the DAG cannot be generated: {exc}")
    drafts: list[Contract] = []
    for path in contracts.values():
        try:
            drafts.append(contract_from_file(path))
        except (DbtGenerationError, OSError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    if drafts:
        for label, build in (("bronze tables", build_bronze), ("dbt models", build_dbt)):
            try:
                build(drafts)
            except (BronzeGenerationError, DbtGenerationError) as exc:
                errors.append(f"the {label} cannot be generated: {exc}")
    return errors


def check_blueprint(dossier_dir: Path) -> Findings:
    """Errors that block Gate H2 and warnings for the reviewer."""

    findings = Findings()
    ingestion_id = dossier_dir.name
    try:
        blueprint = load_blueprint(dossier_dir)
        identity = _identity(blueprint, dossier_dir)
    except Exception as exc:  # noqa: BLE001 - malformed YAML is a finding
        findings.errors.append(f"blueprint.yml: {exc}")
        return findings
    findings.errors.extend(f"blueprint.yml: {e}" for e in identity)

    datasets = blueprint.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        findings.errors.append("blueprint.yml: datasets must declare at least one dataset")
        return findings
    contracts = contract_files(dossier_dir, blueprint)
    for name, dataset in datasets.items():
        findings.errors.extend(
            f"blueprint.yml: {e}"
            for e in _dataset_errors(ingestion_id, name, dataset, contracts.get(name))
        )
    findings.errors.extend(f"blueprint.yml: {e}" for e in _platform_errors(blueprint, ingestion_id))

    # The blueprint must agree with the assessment a human already signed (Gate H1).
    assessment = dossier_dir / "assessment.md"
    if assessment.is_file():
        planned = {
            f
            for f in evidence.payload_formats(assessment.read_text(encoding="utf-8"))
            if f in TIKA_FORMATS
        }
        declared = set(
            (blueprint.get("runtime") or {}).get("triage", {}).get("binary_to_tika") or []
        )
        if planned != declared:
            findings.errors.append(
                f"blueprint.yml: binary_to_tika {sorted(declared)} differs from the assessment "
                f"payload table {sorted(planned)}"
            )
    if not findings.errors:
        findings.errors.extend(_generation_errors(blueprint, ingestion_id, contracts))
    return findings
