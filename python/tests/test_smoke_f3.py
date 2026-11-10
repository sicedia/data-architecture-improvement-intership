"""F3/F4 end-to-end: Airflow (YAML DAG) -> fixture extractor -> RustWorker -> bronze -> dbt.

Needs the three stacks up (`make infra-up`); skipped when Airflow is not running.
Env overrides: AIRFLOW_CONTAINER, POSTGRES_CONTAINER.
"""

import json
import os
import subprocess
import time

import pytest


def _find_container(env_var: str, candidates: tuple[str, ...]) -> str:
    val = os.environ.get(env_var)
    if val:
        return val
    for name in candidates:
        check = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
        )
        if check.returncode == 0 and check.stdout.strip() == "true":
            return name
    return candidates[0]


AIRFLOW = _find_container(
    "AIRFLOW_CONTAINER",
    ("scrapagents-airflow-scheduler", "scrapagents-orchestration-airflow-scheduler-1"),
)
POSTGRES = _find_container(
    "POSTGRES_CONTAINER",
    ("scrapagents-postgres", "scrapagents-warehouse-postgres-1"),
)
DAG_ID = "ingest__fixture"
TIMEOUT_SECONDS = 240


def _run(*cmd: str, check: bool = True) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, check=check)
    return out.stdout.strip()


def _airflow(*args: str, check: bool = True) -> str:
    return _run("docker", "exec", AIRFLOW, "airflow", *args, check=check)


@pytest.fixture(scope="module")
def airflow_up():
    running = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", AIRFLOW], capture_output=True, text=True
    )
    if running.returncode != 0 or running.stdout.strip() != "true":
        pytest.skip("Airflow is not running (make infra-up)")


def _wait_for_dag() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if DAG_ID in _airflow("dags", "list", "-o", "json", check=False):
            return
        time.sleep(2)
    pytest.fail(f"{DAG_ID} was not discovered by the YAML importer")


def _state(run_id: str) -> str:
    runs = json.loads(_airflow("dags", "list-runs", DAG_ID, "-o", "json", check=False) or "[]")
    return next((r["state"] for r in runs if r["run_id"] == run_id), "none")


def test_yaml_dag_runs_end_to_end(airflow_up):
    _wait_for_dag()
    assert _airflow("dags", "list-import-errors", check=False).count("No data found") == 1
    _airflow("dags", "unpause", DAG_ID)
    run_id = f"smoke_{int(time.time())}"
    _airflow("dags", "trigger", DAG_ID, "--run-id", run_id)

    deadline = time.monotonic() + TIMEOUT_SECONDS
    state = "none"
    while time.monotonic() < deadline and state not in ("success", "failed"):
        time.sleep(4)
        state = _state(run_id)
    assert state == "success", f"DAG run ended as {state!r}"

    def psql(sql: str) -> str:
        return _run(
            "docker", "exec", POSTGRES, "psql", "-U", "scrapagents", "-d", "scrapagents",
            "-tA", "-c", sql,
        )  # fmt: skip

    # The records reached their typed bronze table; the unknown binary reached quarantine.
    assert psql("select count(*) from bronze.fixture__records") == "2"
    assert psql(
        "select count(*) from bronze_quarantine.rejected_payloads where source='fixture'"
    ) == "1"

    # The dbt_build task built the three layers from bronze (staging, intermediate, Producto OI).
    for table in (
        "staging.stg_fixture__records",
        "intermediate.int_fixture__records",
        "producto_oi.oi_fixture_catalog",
    ):
        assert psql(f"select count(*) from {table}") == "2", table
    names = (
        "select string_agg(record_name, ',' order by record_id) "
        "from producto_oi.oi_fixture_catalog"
    )
    assert psql(names) == "alpha,beta"
