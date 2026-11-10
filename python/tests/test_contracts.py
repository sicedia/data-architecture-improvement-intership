from scrapagents.contracts import (
    ALLOWED_COLUMN_TYPES,
    iter_contract_files,
    validate_contract,
    validate_contract_file,
)


def _valid() -> dict:
    return {
        "source_system": "demo",
        "dataset": "records",
        "description": "d",
        "owner": "data_team_iditi",
        "grain": "one row per record",
        "primary_key": ["id"],
        "columns": [{"name": "id", "type": "string", "required": True, "description": "id"}],
    }


def test_valid_contract_has_no_errors():
    assert validate_contract(_valid()) == []


def test_reports_missing_field_bad_type_and_owner():
    data = _valid()
    del data["grain"]
    data["owner"] = "iditi"
    data["columns"][0]["type"] = "varchar"
    errors = validate_contract(data)
    assert any("grain" in e for e in errors)
    assert any("owner" in e for e in errors)
    assert any("varchar" in e for e in errors)


def test_personal_column_needs_purpose_and_flag():
    data = _valid()
    data["columns"][0]["classification"] = "personal"
    errors = validate_contract(data)
    assert any("personal_data" in e for e in errors)
    assert any("purpose" in e for e in errors)


def test_every_contract_of_the_repository_passes_the_validator():
    files = list(iter_contract_files())
    assert files
    errors = [e for path in files for e in validate_contract_file(path)]
    assert errors == []


def test_the_validator_rules_are_pinned():
    assert ALLOWED_COLUMN_TYPES == {
        "string",
        "integer",
        "number",
        "boolean",
        "object",
        "array",
        "json",
        "date",
        "timestamp",
    }
