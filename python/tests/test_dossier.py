import pytest
import yaml
from scrapagents.contracts import validate_contract_file
from scrapagents.dossier import (
    DossierError,
    check_dossiers,
    check_producto_oi,
    check_state,
    create_dossier,
    load_dossier,
)


def _state(phase: str, **gates: dict) -> dict:
    base = {n: {"status": "pending", "approved_by": None} for n in ("h1", "h2", "pr")}
    base.update(gates)
    return {"phase": phase, "gates": base}


def test_create_dossier_renders_valid_files(tmp_path):
    path = create_dossier("demo_source", "iditi", root=tmp_path)
    assert {p.name for p in path.iterdir()} == {
        "state.yml",
        "discovery.md",
        "assessment.md",
        "blueprint.yml",
        "contract.yml",
    }
    assert load_dossier(path).state["phase"] == "discovery"
    assert yaml.safe_load((path / "blueprint.yml").read_text())["ingestion_id"] == "demo_source"
    assert validate_contract_file(path / "contract.yml", check_location=False) == []
    assert check_dossiers(tmp_path) == []


def test_create_dossier_rejects_bad_input_and_duplicates(tmp_path):
    with pytest.raises(DossierError):
        create_dossier("Bad-Id", "iditi", root=tmp_path)
    with pytest.raises(DossierError):
        create_dossier("ok", "nobody", root=tmp_path)
    create_dossier("ok", "iditi", root=tmp_path)
    with pytest.raises(DossierError):
        create_dossier("ok", "iditi", root=tmp_path)


def test_phase_cannot_pass_a_pending_gate():
    errors = check_state(_state("blueprint"))
    assert any("gate h1" in e for e in errors)
    assert check_state(_state("assessment")) == []


def test_approved_gate_requires_a_human_name():
    approved = {"status": "approved", "approved_by": None}
    assert any("approved_by" in e for e in check_state(_state("assessment", h1=approved)))
    signed = {"status": "approved", "approved_by": "Ana"}
    assert check_state(_state("blueprint", h1=signed)) == []


def test_done_requires_all_three_gates():
    signed = {"status": "approved", "approved_by": "Ana"}
    assert check_state(_state("done", h1=signed, h2=signed, pr=signed)) == []
    assert check_state(_state("done", h1=signed, h2=signed))


def _oi_layout(tmp_path, gates: dict | None):
    models = tmp_path / "producto_oi"
    (models / "simpler_grants").mkdir(parents=True)
    (models / "fixture").mkdir()  # harness source: exempt
    dossiers = tmp_path / "ingestions"
    if gates is not None:
        (dossiers / "simpler_grants").mkdir(parents=True)
        state = {"phase": "blueprint", "gates": gates}
        (dossiers / "simpler_grants" / "state.yml").write_text(yaml.safe_dump(state))
    return models, dossiers


def _gate(status: str, by: str | None) -> dict:
    return {"status": status, "approved_by": by, "approved_at": None}


def test_producto_oi_of_a_real_source_needs_a_dossier(tmp_path):
    models, dossiers = _oi_layout(tmp_path, None)
    (error,) = check_producto_oi(models, dossiers)
    assert "no dossier ingestions/simpler_grants" in error


def test_producto_oi_needs_h1_and_h2_signed_by_a_human(tmp_path):
    pending = {"h1": _gate("approved", "ana"), "h2": _gate("pending", None)}
    models, dossiers = _oi_layout(tmp_path, pending)
    (error,) = check_producto_oi(models, dossiers)
    assert "gate h2" in error and "not approved" in error

    unsigned = {"h1": _gate("approved", None), "h2": _gate("approved", "ana")}
    models, dossiers = _oi_layout(tmp_path / "b", unsigned)
    (error,) = check_producto_oi(models, dossiers)
    assert "gate h1" in error

    signed = {"h1": _gate("approved", "ana"), "h2": _gate("approved", "luis")}
    models, dossiers = _oi_layout(tmp_path / "c", signed)
    assert check_producto_oi(models, dossiers) == []


def test_repository_producto_oi_respects_the_gates():
    assert check_producto_oi() == []
