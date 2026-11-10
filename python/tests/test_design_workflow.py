"""F5 exit criterion: a new source goes Discovery -> Implement with two human sign-offs recorded.

The agents' work is simulated by writing the evidence files; the humans' by calling ``sign``.
"""

import pytest
import yaml
from design_helpers import fill_assessment, fill_blueprint, fill_discovery, new_dossier
from scrapagents.design import WorkflowError, advance, sign, status
from scrapagents.design.review import review_is_current, write_review
from scrapagents.dossier import check_dossiers, load_dossier


def test_a_new_source_goes_from_discovery_to_implement_with_two_human_signatures(tmp_path):
    dossier = new_dossier(tmp_path)

    # Phase 1: an empty dossier is not ready; the status says exactly what is missing.
    first = status(dossier)
    assert first.phase == "discovery" and not first.can_advance
    assert any("no probe evidence" in b for b in first.blockers)
    with pytest.raises(WorkflowError, match="Institution"):
        advance(dossier)

    fill_discovery(dossier)  # source-scout
    assert advance(dossier) == "assessment"

    # Phase 2: complete evidence is not enough, Gate H1 needs a person.
    assert any("Decision" in b for b in status(dossier).blockers)
    fill_assessment(dossier)  # source-assessor
    waiting = status(dossier)
    assert waiting.blockers == [] and "GATE=h1" in waiting.waiting_for_human
    with pytest.raises(WorkflowError, match="GATE=h1"):
        advance(dossier)
    sign(dossier, "h1", "Ana Torres", today="2026-11-09")
    assert advance(dossier) == "blueprint"

    # Phase 3: the blueprint needs the contract, a fresh review and Gate H2.
    fill_blueprint(dossier)  # silver-designer
    with pytest.raises(WorkflowError, match="review.md is missing or stale"):
        advance(dossier)
    assert write_review(dossier).errors == []  # arch-reviewer
    assert "GATE=h2" in status(dossier).waiting_for_human
    sign(dossier, "h2", "Luis Vera", today="2026-11-10")
    assert advance(dossier) == "implement"

    # The state records who signed what, and the repository checks accept it.
    state = load_dossier(dossier).state
    assert state["phase"] == "implement"
    assert state["gates"]["h1"] == {
        "status": "approved",
        "approved_by": "Ana Torres",
        "approved_at": "2026-11-09",
    }
    assert state["gates"]["h2"]["approved_by"] == "Luis Vera"
    assert state["gates"]["pr"]["status"] == "pending"
    assert check_dossiers(tmp_path) == []
    # Implement is evidenced in this repository: config, contracts and extractor must exist.
    with pytest.raises(WorkflowError, match=r"configs/ingestions/.*is missing"):
        advance(dossier)


def test_signing_keeps_the_comments_of_state_yml(tmp_path):
    dossier = new_dossier(tmp_path)
    fill_discovery(dossier)
    advance(dossier)
    fill_assessment(dossier)
    sign(dossier, "h1", "Ana Torres")
    text = (dossier / "state.yml").read_text(encoding="utf-8")
    assert text.startswith("# Design-time state of ingestion")
    assert yaml.safe_load(text)["gates"]["h1"]["approved_by"] == "Ana Torres"


def test_a_gate_is_signed_by_a_person_in_its_own_phase_with_complete_evidence(tmp_path):
    dossier = new_dossier(tmp_path)
    with pytest.raises(WorkflowError, match="phase 'assessment'"):
        sign(dossier, "h1", "Ana Torres")  # still in discovery
    fill_discovery(dossier)
    advance(dossier)
    with pytest.raises(WorkflowError, match="evidence is incomplete"):
        sign(dossier, "h1", "Ana Torres")  # assessment not written
    fill_assessment(dossier)
    for name in ("claude", "Cursor Agent", "GPT-5", "assistant", " "):
        with pytest.raises(WorkflowError, match="person"):
            sign(dossier, "h1", name)
    with pytest.raises(WorkflowError, match="gate must be"):
        sign(dossier, "h3", "Ana Torres")
    sign(dossier, "h1", "Ana Torres")
    with pytest.raises(WorkflowError, match="already signed"):
        sign(dossier, "h1", "Ana Torres")


def test_a_no_go_assessment_cannot_be_signed_or_advanced(tmp_path):
    dossier = new_dossier(tmp_path)
    fill_discovery(dossier)
    advance(dossier)
    fill_assessment(dossier, decision="no-go")
    assert any("no-go" in b for b in status(dossier).blockers)
    with pytest.raises(WorkflowError, match="no-go"):
        sign(dossier, "h1", "Ana Torres")


def test_h2_cannot_be_signed_on_a_stale_review(tmp_path):
    dossier = new_dossier(tmp_path)
    fill_discovery(dossier)
    advance(dossier)
    fill_assessment(dossier)
    sign(dossier, "h1", "Ana Torres")
    advance(dossier)
    fill_blueprint(dossier)
    write_review(dossier)
    assert review_is_current(dossier)
    # Anything that changes after the review invalidates it.
    blueprint = dossier / "blueprint.yml"
    blueprint.write_text(blueprint.read_text().replace("retries: 2", "retries: 5"))
    assert not review_is_current(dossier)
    with pytest.raises(WorkflowError, match="stale"):
        sign(dossier, "h2", "Luis Vera")
    write_review(dossier)
    sign(dossier, "h2", "Luis Vera")


def test_the_pr_gate_is_signed_in_phase_verify_only(tmp_path):
    dossier = new_dossier(tmp_path)
    with pytest.raises(WorkflowError, match="phase 'verify'"):
        sign(dossier, "pr", "Ana Torres")
