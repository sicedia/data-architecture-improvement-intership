"""F4: dbt models and tests generated from data contracts (design-time)."""

import copy
from pathlib import Path

import pytest
import yaml
from scrapagents.contracts import iter_contract_files, load_yaml
from scrapagents.dbt import DbtGenerationError, build_files, check_files, generate
from scrapagents.dbt.generator import BRONZE_COLUMNS, Contract
from scrapagents.paths import INGESTIONS_DIR, REPO_ROOT

FIXTURE_CONTRACT = INGESTIONS_DIR / "_fixture" / "contracts" / "records.yml"


def col(name: str, type_: str, required: bool = False, **extra) -> dict:
    return {
        "name": name,
        "type": type_,
        "required": required,
        "description": f"{name}.",
        "classification": "public",
    } | extra


def contract(**overrides) -> Contract:
    data = {
        "source_system": "demo",
        "dataset": "people",
        "description": "People.",
        "owner": "data_team_iditi",
        "grain": "one row per person",
        "primary_key": ["person_id"],
        "personal_data": True,
        "columns": [
            col("person_id", "integer", True),
            col("email", "string", classification="personal", purpose="Contact."),
            col("born", "date"),
            col("score", "number", True),
            col("active", "boolean"),
            col("seen", "timestamp"),
            col("tags", "array"),
            col("payload", "json", True),
        ],
    } | overrides
    return Contract(data, "test/people.yml")


def models(files: dict[str, str], path: str) -> dict[str, dict]:
    return {m["name"]: m for m in yaml.safe_load(files[path])["models"]}


def column_tests(model: dict) -> dict[str, list[str]]:
    return {c["name"]: c.get("data_tests", []) for c in model["columns"]}


def test_staging_casts_each_contract_type():
    sql = build_files([contract()])["models/staging/demo/stg_demo__people.sql"]
    assert "(record ->> 'person_id')::bigint as person_id" in sql
    assert "(record ->> 'email')::text as email" in sql
    assert "(record ->> 'born')::date as born" in sql
    assert "(record ->> 'score')::numeric as score" in sql
    assert "(record ->> 'active')::boolean as active" in sql
    assert "(record ->> 'seen')::timestamptz as seen" in sql
    assert "record -> 'tags' as tags" in sql
    assert "    record as payload," in sql
    assert "select * from {{ source('demo', 'people') }}" in sql
    for lineage in ("bronze_batch_id", "bronze_record_hash", "bronze_landing_uri"):
        assert f"    {lineage}," in sql
    assert "_batch_id::text as bronze_batch_id" in sql
    assert '{{ config(tags=["source_demo"]) }}' in sql


def test_tests_follow_the_contract_rules():
    files = build_files([contract()])
    stg = models(files, "models/staging/demo/_stg_demo.yml")["stg_demo__people"]
    tests = column_tests(stg)
    assert tests["person_id"] == ["not_null"]  # required and key
    assert tests["score"] == ["not_null"]  # required
    assert "email" not in {k for k, v in tests.items() if v}  # optional: no test
    assert all(tests[name] == ["not_null"] for name in BRONZE_COLUMNS)
    cur = models(files, "models/intermediate/demo/_int_demo.yml")["int_demo__people"]
    assert column_tests(cur)["person_id"] == ["not_null", "unique"]  # current model: key is unique
    assert "unique" not in column_tests(stg)["person_id"]  # staging keeps every landed version


def test_personal_columns_are_tagged_and_documented():
    stg = models(build_files([contract()]), "models/staging/demo/_stg_demo.yml")["stg_demo__people"]
    email = next(c for c in stg["columns"] if c["name"] == "email")
    assert email["tags"] == ["pii"]
    assert email["meta"] == {"classification": "personal", "purpose": "Contact."}
    assert stg["meta"]["generated"] is True and stg["meta"]["layer"] == "staging"


def test_grain_test_is_always_generated_and_composite_keys_get_a_pk_test():
    files = build_files([contract()])
    grain = files["tests/generated/demo/stg_demo__people__grain.sql"]
    assert "group by person_id, bronze_batch_id" in grain
    assert not any(p.endswith("__pk.sql") for p in files)

    composite = contract(primary_key=["person_id", "born"])
    files = build_files([composite])
    assert "group by person_id, born\n" in files["tests/generated/demo/int_demo__people__pk.sql"]
    cur = models(files, "models/intermediate/demo/_int_demo.yml")["int_demo__people"]
    assert "unique" not in column_tests(cur)["person_id"]  # no single-column unique for a composite
    assert "distinct on (person_id, born)" in files["models/intermediate/demo/int_demo__people.sql"]


def test_only_argument_free_tests_are_generated():
    """`arguments:` differs between dbt versions (unknown to 1.8, required by newer): avoid it."""
    for text in build_files([contract()]).values():
        assert "arguments" not in text and "accepted_values" not in text
    stg = models(build_files([contract()]), "models/staging/demo/_stg_demo.yml")["stg_demo__people"]
    for tests in column_tests(stg).values():
        assert all(isinstance(t, str) for t in tests)


def test_several_datasets_of_a_source_share_one_schema_file():
    other = copy.deepcopy(contract().data) | {"dataset": "orgs"}
    files = build_files([contract(), Contract(other, "test/orgs.yml")])
    assert set(models(files, "models/staging/demo/_stg_demo.yml")) == {
        "stg_demo__people",
        "stg_demo__orgs",
    }


def test_mixed_case_source_columns_are_quoted():
    cols = [col("COLA_Codigo", "string", True), col("payload", "json", True)]
    files = build_files([contract(columns=cols, primary_key=["COLA_Codigo"], personal_data=False)])
    assert '(record ->> \'COLA_Codigo\')::text as "COLA_Codigo"' in files[
        "models/staging/demo/stg_demo__people.sql"
    ]
    assert 'distinct on ("COLA_Codigo")' in files["models/intermediate/demo/int_demo__people.sql"]
    assert 'group by "COLA_Codigo", bronze_batch_id' in files[
        "tests/generated/demo/stg_demo__people__grain.sql"
    ]
    stg = models(files, "models/staging/demo/_stg_demo.yml")["stg_demo__people"]
    assert stg["columns"][0]["quote"] is True
    assert "quote" not in stg["columns"][1]


def test_sources_declare_the_typed_bronze_tables():
    other = copy.deepcopy(contract().data) | {"dataset": "orgs", "primary_key": ["person_id"]}
    files = build_files([contract(), Contract(other, "test/orgs.yml")])
    (source,) = yaml.safe_load(files["models/sources/_src_demo.yml"])["sources"]
    assert source["name"] == "demo" and source["schema"] == "bronze"
    tables = {t["name"]: t for t in source["tables"]}
    assert {n: t["identifier"] for n, t in tables.items()} == {
        "people": "demo__people",
        "orgs": "demo__orgs",
    }
    columns = {c["name"]: c.get("data_tests") for c in tables["people"]["columns"]}
    assert columns["person_id"] == ["not_null"]  # the key column
    for lineage in ("payload", "_batch_id", "_landing_uri", "_record_hash", "_ingested_at"):
        assert columns[lineage] == ["not_null"]


def test_mixed_case_keys_are_quoted_in_the_source():
    cols = [col("COLA_Codigo", "string", True), col("payload", "json", True)]
    files = build_files([contract(columns=cols, primary_key=["COLA_Codigo"], personal_data=False)])
    (source,) = yaml.safe_load(files["models/sources/_src_demo.yml"])["sources"]
    assert source["tables"][0]["columns"][0] == {
        "name": "COLA_Codigo",
        "data_tests": ["not_null"],
        "quote": True,
    }


def test_generation_is_deterministic():
    assert build_files([contract()]) == build_files([contract()])


@pytest.mark.parametrize(
    "change, message",
    [
        ({"primary_key": ["missing"]}, "primary key"),
        ({"source_system": "Bad Name"}, "identifier"),
        ({"owner": "someone"}, "owner"),
    ],
)
def test_invalid_contracts_are_rejected(change, message):
    with pytest.raises(DbtGenerationError, match=message):
        build_files([contract(**change)])


def test_reserved_and_duplicate_columns_are_rejected():
    cols = contract().data["columns"]
    reserved = [*cols, col("bronze_batch_id", "string")]
    with pytest.raises(DbtGenerationError, match="reserved"):
        build_files([contract(columns=reserved)])
    with pytest.raises(DbtGenerationError, match="duplicate"):
        build_files([contract(columns=[*cols, cols[0]])])


@pytest.mark.parametrize(
    "path", sorted(iter_contract_files()), ids=lambda p: f"{p.parent.name}/{p.stem}"
)
def test_every_contract_of_the_repository_generates_valid_output(path):
    data = load_yaml(path)
    files = build_files([Contract(data, "configs")])
    stg = models(files, f"models/staging/{data['source_system']}/_stg_{data['source_system']}.yml")
    name = f"stg_{data['source_system']}__{data['dataset']}"
    assert [c["name"] for c in stg[name]["columns"]][: len(data["columns"])] == [
        c["name"] for c in data["columns"]
    ]


def test_committed_dbt_files_match_their_contracts():
    catalog = [(c.parent.name, c.stem) for c in iter_contract_files()]
    files, errors = generate([FIXTURE_CONTRACT], catalog)
    assert errors == []
    assert check_files(files, REPO_ROOT / "dbt") == []


def test_check_detects_drift_and_orphans(tmp_path: Path):
    files, _ = generate([FIXTURE_CONTRACT], [])
    assert any("missing" in p for p in check_files(files, tmp_path))
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content)
    assert check_files(files, tmp_path) == []
    stale = tmp_path / "models/staging/fixture/stg_fixture__records.sql"
    stale.write_text(stale.read_text() + "\n-- edited by hand")
    orphan = tmp_path / "models/staging/ghost/stg_ghost__x.sql"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("-- Generated by `scrapagents generate-dbt` from gone.yml.\nselect 1")
    problems = "\n".join(check_files(files, tmp_path))
    assert "out of date" in problems and "no contract generates it" in problems


def test_hand_written_models_are_not_treated_as_generated():
    assert (REPO_ROOT / "dbt/models/producto_oi/fixture/oi_fixture_catalog.sql").is_file()
    files, _ = generate([FIXTURE_CONTRACT], [])
    assert not any(rel.startswith("models/producto_oi") for rel in files)
