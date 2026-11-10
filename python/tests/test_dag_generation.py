"""F3: declarative Airflow DAGs generated from ingestion configs (design-time)."""

import json
from pathlib import Path

import pytest
import yaml
from scrapagents.contracts.loader import load_ingestion_config
from scrapagents.dags import ALLOWED_OPERATORS, DagGenerationError, build_dag, check_dags, generate
from scrapagents.dags import generator as gen
from scrapagents.dags.generator import SCHEMA_URL, pools_json
from scrapagents.dossier import create_dossier
from scrapagents.paths import INGESTIONS_DIR, REPO_ROOT, config_root

FIXTURE_CONFIG = INGESTIONS_DIR / "_fixture" / "ingestion.yml"
CONFIG_IDS = sorted(p.stem for p in (config_root() / "configs" / "ingestions").glob("*.yml"))


def parsed(dag) -> dict:
    return yaml.safe_load(dag.content)


def base_config(**airflow) -> dict:
    return {
        "ingestion_id": "demo",
        "datasets": {"records": {}, "files": {}},
        "airflow": airflow,
    }


def test_document_follows_the_airflow_yaml_format():
    dag = build_dag(base_config(retries=2, retry_delay_minutes=3, pool="demo_pool"), "x")
    doc = parsed(dag)
    assert doc["$schema"] == SCHEMA_URL
    assert doc["dag_id"] == "ingest__demo"
    tasks = {t["id"]: t for t in doc["tasks"]}
    assert list(tasks) == ["runtime_ready", "land__records", "land__files", "landed"]  # no dbt
    assert tasks["land__records"]["needs"] == ["runtime_ready"]
    assert tasks["landed"]["needs"] == ["land__records", "land__files"]
    assert tasks["land__records"]["pool"] == "demo_pool"
    assert tasks["land__records"]["retries"] == 2
    assert tasks["land__records"]["retry_delay"] == "3m"
    assert tasks["land__records"]["with"]["bash_command"] == {
        "$t": "python -m scrapagents.extractors.demo --dataset records"
        " --ingest-date {{ (dag_run.logical_date or dag_run.run_after).strftime('%Y-%m-%d') }}"
    }


def test_schedule_comes_from_the_config():
    assert parsed(build_dag(base_config(), "x"))["schedule"] is None
    assert parsed(build_dag(base_config(schedule="30 6 * * 2"), "x"))["schedule"] == "30 6 * * 2"
    for bad in ("daily", "* * *", 5):
        with pytest.raises(DagGenerationError):
            build_dag(base_config(schedule=bad), "x")


def test_invalid_configs_are_rejected():
    with pytest.raises(DagGenerationError):
        build_dag({"ingestion_id": "Bad Id", "datasets": {"a": {}}}, "x")
    with pytest.raises(DagGenerationError):
        build_dag({"ingestion_id": "demo", "datasets": {}}, "x")
    with pytest.raises(DagGenerationError):
        build_dag(base_config(retries=-1), "x")
    with pytest.raises(DagGenerationError):
        build_dag(base_config(pool="Bad Pool"), "x")


def test_dbt_step_follows_landing_and_uses_the_config_selector():
    config = base_config()
    config["dbt"] = {"selector": "tag:source_demo"}
    tasks = {t["id"]: t for t in parsed(build_dag(config, "x"))["tasks"]}
    assert tasks["dbt_build"]["needs"] == ["landed"]
    assert tasks["dbt_build"]["with"]["bash_command"] == (
        'cd "$DBT_PROJECT_DIR" && "$DBT_BIN" build --select tag:source_demo'
    )
    config["dbt"] = {"selector": "tag:x; rm -rf /"}
    with pytest.raises(DagGenerationError, match="dbt.selector"):
        build_dag(config, "x")


def test_extractor_command_placeholders_and_airflow_templates():
    config = base_config()
    config["runtime"] = {
        "extractor": {"command": "run {ingestion_id} {dataset} --d {ingest_date} --raw {{ ds }}"}
    }
    command = parsed(build_dag(config, "x"))["tasks"][1]["with"]["bash_command"]["$t"]
    assert command.startswith("run demo records --d {{ (dag_run.logical_date or ")
    assert command.endswith("--raw {{ ds }}")


def test_generation_is_deterministic_and_uses_only_allowed_operators():
    first = build_dag(base_config(pool="p"), "x")
    assert first.content == build_dag(base_config(pool="p"), "x").content
    assert {t["uses"] for t in parsed(first)["tasks"]} <= ALLOWED_OPERATORS


def test_pools_document():
    dags = [build_dag(base_config(pool="a_pool", pool_slots=3, pool_description="d"), "x")]
    assert json.loads(pools_json(dags)) == {
        "a_pool": {"description": "d", "include_deferred": False, "slots": 3}
    }
    assert json.loads(pools_json([build_dag(base_config(), "x")])) == {}


@pytest.mark.parametrize("ingestion_id", CONFIG_IDS)
def test_every_configured_ingestion_generates_a_dag(ingestion_id):
    config = load_ingestion_config(ingestion_id)
    doc = parsed(build_dag(config, "x"))
    assert doc["dag_id"] == f"ingest__{ingestion_id}"
    assert doc["schedule"] == config["airflow"]["schedule"]
    extra = 3 if (config.get("dbt") or {}).get("selector") else 2  # + runtime_ready, landed, dbt
    assert len(doc["tasks"]) == len(config["datasets"]) + extra


def test_committed_dags_match_their_sources():
    dags, errors = generate(CONFIG_IDS, [FIXTURE_CONFIG])
    assert errors == []
    assert check_dags(dags, REPO_ROOT / "dags") == []


def test_check_detects_drift_and_orphans(tmp_path):
    dags, _ = generate([], [FIXTURE_CONFIG])
    assert any("missing" in p for p in check_dags(dags, tmp_path))
    (tmp_path / "ingest__fixture.yml").write_text("stale")
    (tmp_path / "ingest__ghost.yml").write_text("orphan")
    problems = "\n".join(check_dags(dags, tmp_path))
    assert "out of date" in problems and "no source config generates it" in problems


def test_dossier_dags_need_an_approved_h2(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "INGESTIONS_DIR", tmp_path)
    dossier = create_dossier("demo_src", "iditi", root=tmp_path)
    with pytest.raises(DagGenerationError, match="Gate H2"):
        gen.resolve_source("demo_src")

    state = yaml.safe_load((dossier / "state.yml").read_text())
    state["gates"]["h2"] = {"status": "approved", "approved_by": "", "approved_at": None}
    (dossier / "state.yml").write_text(yaml.safe_dump(state))
    with pytest.raises(DagGenerationError, match="Gate H2"):
        gen.resolve_source("demo_src")  # approved without a named approver is still refused

    state["gates"]["h2"]["approved_by"] = "owner@example.org"
    (dossier / "state.yml").write_text(yaml.safe_dump(state))
    config, ref = gen.resolve_source("demo_src")
    assert ref == "ingestions/demo_src/blueprint.yml"
    assert parsed(build_dag(config, ref))["dag_id"] == "ingest__demo_src"


def test_unknown_source_is_reported(tmp_path: Path):
    _, errors = generate(["does_not_exist"], [])
    assert errors and "does_not_exist" in errors[0]
