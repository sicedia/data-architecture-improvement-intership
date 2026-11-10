"""F4: typed bronze tables and the runtime registry generated from data contracts."""

import copy
import json
import re

import pytest
from scrapagents.bronze import BronzeGenerationError, build_files, check_files, generate
from scrapagents.bronze.generator import BRONZE_DIR
from scrapagents.contracts import iter_contract_files
from scrapagents.dbt.generator import Contract
from scrapagents.paths import INGESTIONS_DIR
from test_dbt_generation import col, contract

FIXTURE_CONTRACT = INGESTIONS_DIR / "_fixture" / "contracts" / "records.yml"


def test_ddl_follows_the_bronze_shape():
    sql = build_files([contract()])["tables.sql"]
    assert "CREATE SCHEMA IF NOT EXISTS bronze;" in sql
    table = sql[sql.index("CREATE TABLE IF NOT EXISTS bronze.demo__people") :]
    for line in (
        "    person_id TEXT NOT NULL,",
        "    payload JSONB NOT NULL,",
        "    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),",
        "    _batch_id UUID NOT NULL,",
        "    _landing_uri TEXT NOT NULL,",
        "    _record_hash TEXT NOT NULL,",
        "    PRIMARY KEY (person_id, _batch_id)",
    ):
        assert line in table
    assert "ix_demo__people_batch ON bronze.demo__people (_batch_id)" in table


def test_registry_lists_tables_and_keys_in_contract_order():
    composite = contract(primary_key=["person_id", "born"])
    registry = json.loads(build_files([composite])["registry.json"])
    assert registry["datasets"] == {
        "demo/people": {"table": "demo__people", "keys": ["person_id", "born"]}
    }


def test_mixed_case_keys_are_quoted_in_the_ddl():
    cols = [col("COLA_Codigo", "string", True), col("payload", "json", True)]
    c = contract(columns=cols, primary_key=["COLA_Codigo"], personal_data=False)
    sql = build_files([c])["tables.sql"]
    assert '    "COLA_Codigo" TEXT NOT NULL,' in sql
    assert 'PRIMARY KEY ("COLA_Codigo", _batch_id)' in sql
    # The registry keeps the real spelling: the runtime quotes it.
    assert json.loads(build_files([c])["registry.json"])["datasets"]["demo/people"]["keys"] == [
        "COLA_Codigo"
    ]


def test_output_does_not_depend_on_input_order():
    other = copy.deepcopy(contract().data) | {"dataset": "orgs"}
    a, b = contract(), Contract(other, "test/orgs.yml")
    assert build_files([a, b]) == build_files([b, a])


def test_invalid_contracts_are_rejected():
    long_dataset = "d" * 60
    cases = {
        "reserved key": contract(
            columns=[col("_batch_id", "string", True), col("payload", "json", True)],
            primary_key=["_batch_id"],
            personal_data=False,
        ),
        "table name too long": contract(dataset=long_dataset),
    }
    for name, c in cases.items():
        with pytest.raises(BronzeGenerationError):
            build_files([c])
            raise AssertionError(name)


def test_a_table_declared_twice_is_rejected():
    with pytest.raises(BronzeGenerationError, match="twice"):
        build_files([contract(), contract()])


def test_committed_bronze_matches_the_contracts():
    catalog = [(c.parent.name, c.stem) for c in iter_contract_files()]
    files, errors = generate([FIXTURE_CONTRACT], catalog)
    assert errors == []
    assert check_files(files, BRONZE_DIR) == []


def test_drift_is_detected(tmp_path):
    files, _ = generate([FIXTURE_CONTRACT], [])
    assert len(check_files(files, tmp_path)) == 2  # both files missing
    (tmp_path / "tables.sql").write_text("-- edited", encoding="utf-8")
    assert any("out of date" in p for p in check_files(files, tmp_path))


def test_every_contract_of_the_repository_generates_a_table():
    catalog = [
        (c.parent.name, c.stem) for c in iter_contract_files() if not c.parent.name.startswith("_")
    ]
    assert ("idrc", "funding_opportunities") in catalog
    files, errors = generate([], catalog)
    assert errors == []
    registry = json.loads(files["registry.json"])["datasets"]
    assert set(registry) == {f"{s}/{d}" for s, d in catalog}
    # Same naming as the `bronze_table` of configs/ingestions/*.yml.
    assert all(v["table"] == k.replace("/", "__") for k, v in registry.items())
    assert len(re.findall("CREATE TABLE IF NOT EXISTS", files["tables.sql"])) == len(catalog)
