"""Design-time generation of declarative Airflow DAGs (YAML, AIP-85) from ingestion configs.

The input is the declaration of a source: ``configs/ingestions/<id>.yml`` or the
blueprint of a dossier whose Gate H2 is approved. The output is a ``.yml`` DAG for Airflow's
YAML importer: no Python code and no LLM (invariant 1). Generation is deterministic, so the
committed DAGs can be checked against their sources (``generate-dags --check``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2

from scrapagents.contracts.loader import load_ingestion_config, load_yaml
from scrapagents.dossier import DossierError, load_dossier
from scrapagents.paths import INGESTIONS_DIR, REPO_ROOT

# `$schema` of the YAML format shipped with Airflow 3.4.0 (airflow.sdk.importers.yaml_importer).
SCHEMA_URL = "https://airflow.apache.org/schemas/dag/2026-10-30.json"
BASH_OPERATOR = "airflow.providers.standard.operators.bash.BashOperator"
EMPTY_OPERATOR = "airflow.providers.standard.operators.empty.EmptyOperator"
# The only operators generated DAGs may use; tests assert nothing else (and no LLM SDK) appears.
ALLOWED_OPERATORS = frozenset({BASH_OPERATOR, EMPTY_OPERATOR})

# Convention (`scrapagents.extractors.<id>`); a config can override it in `runtime.extractor`.
DEFAULT_EXTRACTOR_COMMAND = (
    "python -m scrapagents.extractors.{ingestion_id}"
    " --dataset {dataset} --ingest-date {ingest_date}"
)
# Landing partition of a run. Airflow 3 manual runs have no `logical_date` (so no `ds`):
# fall back to `dag_run.run_after`, which every run has. Same value on every retry of a run.
INGEST_DATE_EXPR = "{{ (dag_run.logical_date or dag_run.run_after).strftime('%Y-%m-%d') }}"
READY_COMMAND = "python -m scrapagents.cli check-runtime"
# dbt runs in the Airflow image from its own virtualenv; the container sets these variables.
DBT_COMMAND = 'cd "$DBT_PROJECT_DIR" && "$DBT_BIN" build --select {selector}'
_DBT_SELECTOR = re.compile(r"^[A-Za-z0-9_:.+*@, -]+$")
START_DATE = "2026-01-01"
POOLS_FILE = "_pools.json"

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_CRON = re.compile(r"^(\S+\s+){4}\S+$")


class DagGenerationError(ValueError):
    pass


@dataclass(frozen=True)
class GeneratedDag:
    dag_id: str
    filename: str
    content: str
    pool: dict[str, Any] | None  # {"name", "slots", "description"} when the config declares a pool


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


_ENV = jinja2.Environment(
    loader=jinja2.PackageLoader("scrapagents.dags", "templates"),
    undefined=jinja2.StrictUndefined,
    trim_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,
)
_ENV.filters["j"] = _j


def _positive_int(value: Any, field: str, default: int, minimum: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DagGenerationError(f"airflow.{field} must be an integer >= {minimum}, got {value!r}")
    return value


def validate_config(config: dict[str, Any]) -> None:
    ingestion_id = config.get("ingestion_id")
    if not isinstance(ingestion_id, str) or not _NAME.match(ingestion_id):
        raise DagGenerationError(f"ingestion_id must match {_NAME.pattern}, got {ingestion_id!r}")
    datasets = config.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        raise DagGenerationError(f"{ingestion_id}: datasets must be a non-empty mapping")
    for name in datasets:
        if not isinstance(name, str) or not _NAME.match(name):
            raise DagGenerationError(f"{ingestion_id}: dataset name {name!r} is not valid")
    schedule = (config.get("airflow") or {}).get("schedule")
    if schedule is not None and not (isinstance(schedule, str) and _CRON.match(schedule.strip())):
        raise DagGenerationError(
            f"{ingestion_id}: airflow.schedule must be null or a 5-field cron, got {schedule!r}"
        )


def build_dag(config: dict[str, Any], source_ref: str) -> GeneratedDag:
    validate_config(config)
    ingestion_id: str = config["ingestion_id"]
    airflow = config.get("airflow") or {}
    extractor = (config.get("runtime") or {}).get("extractor") or {}
    template = extractor.get("command", DEFAULT_EXTRACTOR_COMMAND)
    if not isinstance(template, str) or not template.strip():
        raise DagGenerationError(f"{ingestion_id}: runtime.extractor.command must be a string")

    retries = _positive_int(airflow.get("retries"), "retries", 0)
    retry_minutes = _positive_int(airflow.get("retry_delay_minutes"), "retry_delay_minutes", 5, 1)
    timeout_hours = _positive_int(airflow.get("land_timeout_hours"), "land_timeout_hours", 4, 1)
    max_runs = _positive_int(airflow.get("max_active_runs"), "max_active_runs", 1, 1)
    pool = airflow.get("pool")
    if pool is not None and not (isinstance(pool, str) and _NAME.match(pool)):
        raise DagGenerationError(f"{ingestion_id}: airflow.pool {pool!r} is not valid")

    datasets = [
        {
            "name": name,
            # Plain replacement, not str.format: the command may carry Airflow's own `{{ ... }}`.
            "command": template.replace("{ingestion_id}", ingestion_id)
            .replace("{dataset}", name)
            .replace("{ingest_date}", INGEST_DATE_EXPR),
        }
        for name in config["datasets"]
    ]
    tags = ["ingestion", f"source_{ingestion_id}"]
    for key in ("source_type", "owning_team"):
        if config.get(key):
            tags.append(str(config[key]))

    selector = (config.get("dbt") or {}).get("selector")
    if selector is not None and not (isinstance(selector, str) and _DBT_SELECTOR.match(selector)):
        raise DagGenerationError(f"{ingestion_id}: dbt.selector {selector!r} is not valid")

    dag_id = f"ingest__{ingestion_id}"
    content = _ENV.get_template("dag.yml.j2").render(
        source_ref=source_ref,
        schema_url=SCHEMA_URL,
        dag_id=dag_id,
        description=config.get("description") or f"Ingestion of {ingestion_id}.",
        schedule=airflow.get("schedule"),
        start_date=START_DATE,
        max_active_runs=max_runs,
        tags=tags,
        bash_operator=BASH_OPERATOR,
        empty_operator=EMPTY_OPERATOR,
        retries=retries,
        retry_delay=f"{retry_minutes}m",
        execution_timeout=f"{timeout_hours}h",
        ready_command=READY_COMMAND,
        pool=pool,
        datasets=datasets,
        land_task_ids=[f"land__{d['name']}" for d in datasets],
        dbt_command=DBT_COMMAND.format(selector=selector) if selector else None,
    )
    pool_def = None
    if pool:
        pool_def = {
            "name": pool,
            "slots": _positive_int(airflow.get("pool_slots"), "pool_slots", 1, 1),
            "description": airflow.get("pool_description") or f"{ingestion_id} extraction",
        }
    return GeneratedDag(dag_id, f"{dag_id}.yml", content, pool_def)


def pools_json(dags: list[GeneratedDag]) -> str:
    """Airflow `pools import` document for every pool declared by ``dags``."""
    pools = {
        d.pool["name"]: {
            "description": d.pool["description"],
            "slots": d.pool["slots"],
            "include_deferred": False,
        }
        for d in dags
        if d.pool
    }
    return json.dumps(pools, indent=2, sort_keys=True) + "\n"


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def resolve_source(ingestion_id: str) -> tuple[dict[str, Any], str]:
    """``configs/ingestions/<id>.yml``, else the blueprint of an H2-approved dossier."""
    try:
        config = load_ingestion_config(ingestion_id)
    except FileNotFoundError:
        pass
    else:
        return config, f"configs/ingestions/{ingestion_id}.yml"
    dossier_dir = INGESTIONS_DIR / ingestion_id
    if not (dossier_dir / "state.yml").is_file():
        raise DagGenerationError(f"no configs/ingestions file nor dossier for {ingestion_id!r}")
    gate = (load_dossier(dossier_dir).state.get("gates") or {}).get("h2") or {}
    if gate.get("status") != "approved" or not gate.get("approved_by"):
        raise DagGenerationError(
            f"{ingestion_id}: Gate H2 is not approved; "
            "DAGs are generated only after a human signs it"
        )
    return load_yaml(dossier_dir / "blueprint.yml"), f"ingestions/{ingestion_id}/blueprint.yml"


def load_config_file(path: Path) -> tuple[dict[str, Any], str]:
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise DagGenerationError(f"{path}: source config must be a mapping")
    return data, _display(path)


def generate(
    ids: list[str], config_files: list[Path]
) -> tuple[list[GeneratedDag], list[str]]:
    """Generate every requested DAG; returns them with the per-source errors."""
    dags: list[GeneratedDag] = []
    errors: list[str] = []
    sources: list[tuple[str, Any]] = [(i, None) for i in ids] + [(str(p), p) for p in config_files]
    for label, path in sources:
        try:
            config, ref = load_config_file(path) if path else resolve_source(label)
            dags.append(build_dag(config, ref))
        except (DagGenerationError, DossierError, FileNotFoundError, ValueError) as exc:
            errors.append(f"{label}: {exc}")
    seen: set[str] = set()
    for dag in dags:
        if dag.dag_id in seen:
            errors.append(f"duplicate dag_id {dag.dag_id}")
        seen.add(dag.dag_id)
    return dags, errors


def write_dags(dags: list[GeneratedDag], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for dag in dags:
        target = out_dir / dag.filename
        target.write_text(dag.content, encoding="utf-8", newline="\n")
        written.append(target)
    pools = out_dir / POOLS_FILE
    pools.write_text(pools_json(dags), encoding="utf-8", newline="\n")
    written.append(pools)
    return written


def check_dags(dags: list[GeneratedDag], out_dir: Path) -> list[str]:
    """Differences between the generated output and the files committed in ``out_dir``."""
    problems: list[str] = []
    expected = {d.filename: d.content for d in dags} | {POOLS_FILE: pools_json(dags)}
    for name, content in expected.items():
        path = out_dir / name
        if not path.is_file():
            problems.append(f"{path}: missing (run `make generate-dags`)")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"{path}: out of date with its source (run `make generate-dags`)")
    if out_dir.is_dir():
        for path in sorted(out_dir.glob("ingest__*.yml")):
            if path.name not in expected:
                problems.append(f"{path}: no source config generates it")
    return problems
