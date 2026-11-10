"""F5: mechanical checks behind the agents (evidence, blueprint, review, probes, CLI)."""

import sys
from types import SimpleNamespace

import pytest
import yaml
from design_helpers import (
    TODAY,
    FakeRouter,
    add_table_row,
    fill_assessment,
    fill_blueprint,
    fill_discovery,
    new_dossier,
)
from scrapagents import cli
from scrapagents.design import evidence
from scrapagents.design.blueprint import check_blueprint
from scrapagents.design.probes import ProbeRow, append_rows, probe, robots_url
from scrapagents.design.review import NOTES_MARKER, review, write_review
from scrapagents.dossier import load_dossier
from scrapagents.stealth.base import PageSnapshot


def ready_blueprint(tmp_path, ingestion_id="acme_grants", **kwargs):
    dossier = new_dossier(tmp_path, ingestion_id, **kwargs)
    fill_discovery(dossier)
    fill_assessment(dossier)
    fill_blueprint(dossier)
    return dossier


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


# --- evidence -------------------------------------------------------------------------------------


def test_the_template_is_incomplete_and_a_filled_dossier_is_not(tmp_path):
    dossier = new_dossier(tmp_path)
    assert len(evidence.discovery_issues((dossier / "discovery.md").read_text())) >= 9
    assert len(evidence.assessment_issues((dossier / "assessment.md").read_text())) >= 9
    fill_discovery(dossier)
    fill_assessment(dossier)
    assert evidence.discovery_issues((dossier / "discovery.md").read_text()) == []
    assert evidence.assessment_issues((dossier / "assessment.md").read_text()) == []


def test_a_todo_does_not_count_as_an_answer(tmp_path):
    dossier = new_dossier(tmp_path)
    fill_discovery(dossier)
    edit(dossier / "discovery.md", "- Authentication: none", "- Authentication: TODO")
    assert any(
        "Authentication" in i
        for i in evidence.discovery_issues((dossier / "discovery.md").read_text())
    )


def test_probe_rows_must_be_well_formed_and_reach_the_site(tmp_path):
    dossier = new_dossier(tmp_path)
    fill_discovery(dossier, status="error")
    issues = evidence.discovery_issues((dossier / "discovery.md").read_text())
    assert issues == ["discovery.md: no probe got an HTTP answer"]
    add_table_row(dossier / "discovery.md", "| Date", ["yesterday", "ftp://x", "ok", "-", "maybe"])
    text = (dossier / "discovery.md").read_text()
    joined = " ".join(evidence.discovery_issues(text))
    for fragment in ("bad date", "bad URL", "bad status", "Blocked by"):
        assert fragment in joined


@pytest.mark.parametrize(
    ("fmt", "tika", "fragment"),
    [
        ("html", "yes", "html never goes to Tika"),
        ("pdf", "no", "pdf must go to Tika"),
        ("docx", "yes", None),
        ("csv", "no", None),
        ("xml", "no", None),
        ("rtf", "no", "format must be"),
    ],
)
def test_invariant_4_is_checked_in_the_payload_table(tmp_path, fmt, tika, fragment):
    dossier = new_dossier(tmp_path)
    fill_assessment(dossier, extra_rows=[("Some payload", fmt, tika)])
    issues = evidence.assessment_issues((dossier / "assessment.md").read_text())
    if fragment is None:
        assert issues == []
    else:
        assert any(fragment in i for i in issues), issues


def test_yes_no_answers_and_the_decision_are_validated(tmp_path):
    dossier = new_dossier(tmp_path)
    fill_assessment(dossier, decision="maybe", personal="perhaps")
    issues = " ".join(evidence.assessment_issues((dossier / "assessment.md").read_text()))
    assert "Personal data' must start with yes or no" in issues
    assert "Decision must be 'go' or 'no-go'" in issues


# --- blueprint ------------------------------------------------------------------------------------


def test_a_complete_blueprint_passes_and_generates_every_artifact(tmp_path):
    dossier = ready_blueprint(tmp_path)
    assert check_blueprint(dossier).errors == []


def test_the_untouched_template_blueprint_fails_on_its_todos(tmp_path):
    findings = check_blueprint(new_dossier(tmp_path))
    joined = " ".join(findings.errors)
    assert "description is missing or still a TODO" in joined
    assert "grain is still a TODO" in joined


@pytest.mark.parametrize(
    ("old", "new", "fragment"),
    [
        ("bronze_table: acme_grants__records", "bronze_table: other", "bronze_table must be"),
        ("landing_format: json ", "landing_format: jsonl ", "landing_format"),
        ("selector: tag:source_acme_grants", "selector: tag:other", "dbt.selector"),
        ("  pool: acme_grants_source", "  pool_x: 1", "airflow.pool is required"),
        ("  schedule: null", "  schedule_x: null", "airflow.schedule must be declared"),
        ("binary_to_tika: []", "binary_to_tika: [html]", "invariant 4"),
        ("owner: data_team_iditi", "owner: someone", "owner must be"),
        ("source_system: acme_grants", "source_system: other", "source_system must be"),
        ("contract: contract.yml", "contract: ../../etc/passwd", "must name a contract file"),
    ],
)
def test_blueprint_violations_are_reported(tmp_path, old, new, fragment):
    dossier = ready_blueprint(tmp_path)
    edit(dossier / "blueprint.yml", old, new)
    errors = check_blueprint(dossier).errors
    assert any(fragment in e for e in errors), errors


def test_blueprint_must_match_the_assessment_about_tika(tmp_path):
    dossier = new_dossier(tmp_path)
    fill_discovery(dossier)
    fill_assessment(dossier, extra_rows=[("Call document", "pdf", "yes")])
    fill_blueprint(dossier)
    assert any("differs from the assessment" in e for e in check_blueprint(dossier).errors)
    edit(dossier / "blueprint.yml", "binary_to_tika: []", "binary_to_tika: [pdf]")
    assert check_blueprint(dossier).errors == []


def test_a_web_source_must_declare_stealth(tmp_path):
    dossier = ready_blueprint(tmp_path, "acme_portal", source_type="web")
    assert check_blueprint(dossier).errors == []
    edit(dossier / "blueprint.yml", "    stealth: true", "    stealth: false")
    assert any("stealth" in e for e in check_blueprint(dossier).errors)


def test_the_draft_contract_is_validated_by_the_contract_rules(tmp_path):
    dossier = ready_blueprint(tmp_path)
    edit(dossier / "contract.yml", "type: string", "type: text")
    assert any("type 'text'" in e for e in check_blueprint(dossier).errors)


def test_persistence_key_must_equal_the_primary_key(tmp_path):
    dossier = ready_blueprint(tmp_path)
    edit(
        dossier / "blueprint.yml",
        "    bronze_table: acme_grants__records\n",
        "    bronze_table: acme_grants__records\n    persistence: {mode: changes, key: [other]}\n",
    )
    assert any("persistence.key" in e for e in check_blueprint(dossier).errors)


def test_several_datasets_each_need_their_own_contract(tmp_path):
    dossier = ready_blueprint(tmp_path)
    edit(
        dossier / "blueprint.yml",
        "airflow:",
        "  orgs:\n    contract: contracts/orgs.yml\n    bronze_table: acme_grants__orgs\nairflow:",
    )
    assert any("datasets.orgs.contract" in e for e in check_blueprint(dossier).errors)
    contract = yaml.safe_load((dossier / "contract.yml").read_text())
    contract["dataset"] = "orgs"
    (dossier / "contracts").mkdir()
    (dossier / "contracts" / "orgs.yml").write_text(yaml.safe_dump(contract))
    assert check_blueprint(dossier).errors == []


# --- review ---------------------------------------------------------------------------------------


def test_a_source_the_project_already_declares_is_a_duplicate_acquisition_path(
    tmp_path, monkeypatch
):
    root = tmp_path / "catalog"
    (root / "configs" / "contracts").mkdir(parents=True)
    (root / "configs" / "ingestions").mkdir(parents=True)
    (root / "configs" / "ingestions" / "simpler_grants.yml").write_text(
        "ingestion_id: simpler_grants\n"
    )
    monkeypatch.setenv("SCRAPAGENTS_CONFIG_ROOT", str(root))
    dossier = ready_blueprint(tmp_path, "simpler_grants")
    assert any("already declares" in e for e in review(dossier).errors)


def test_personal_data_must_be_consistent_between_assessment_and_contract(tmp_path):
    dossier = ready_blueprint(tmp_path)
    edit(dossier / "contract.yml", "primary_key:", "personal_data: true\nprimary_key:")
    errors = review(dossier).errors
    assert any("personal_data: true, but the assessment says no" in e for e in errors), errors


def test_code_in_a_dossier_obeys_invariants_1_and_3(tmp_path):
    dossier = ready_blueprint(tmp_path)
    (dossier / "probe.py").write_text("import anthropic\nfrom playwright.sync_api import x\n")
    errors = " ".join(review(dossier).errors)
    assert "imports anthropic" in errors and "imports playwright directly" in errors


def test_an_llm_in_the_extractor_command_is_rejected(tmp_path):
    dossier = ready_blueprint(tmp_path)
    edit(
        dossier / "blueprint.yml",
        "runtime:\n",
        "runtime:\n  extractor:\n    command: python -m openai.run {dataset}\n",
    )
    assert any("mentions openai" in e for e in review(dossier).errors)


def test_party_like_columns_are_flagged_for_the_reviewer(tmp_path):
    dossier = ready_blueprint(tmp_path)
    contract = yaml.safe_load((dossier / "contract.yml").read_text())
    contract["columns"].append(
        {"name": "author_name", "type": "string", "required": False, "description": "Author."}
    )
    (dossier / "contract.yml").write_text(yaml.safe_dump(contract))
    assert any("author_name" in w and "Party" in w for w in review(dossier).warnings)


def test_reviewer_notes_survive_a_regeneration(tmp_path):
    dossier = ready_blueprint(tmp_path)
    write_review(dossier)
    path = dossier / "review.md"
    path.write_text(path.read_text().replace(
        "(arch-reviewer: judgement on ownership, shared source vs product, Party, refresh)",
        "Shared Source Integration: reusable, no product semantics.",
    ))  # fmt: skip
    write_review(dossier)
    text = path.read_text()
    assert NOTES_MARKER in text and "Shared Source Integration: reusable" in text
    assert "Result: pass" in text


def test_a_failing_review_is_recorded_as_such(tmp_path):
    dossier = new_dossier(tmp_path)  # template: TODOs
    assert write_review(dossier).errors
    assert "Result: fail" in (dossier / "review.md").read_text()


# --- probes ---------------------------------------------------------------------------------------


def test_probe_visits_robots_once_per_host_and_records_blocks_and_failures():
    url_a, url_b = "https://x.example/a", "https://x.example/b?q=1"
    router = FakeRouter(
        {
            "https://x.example/robots.txt": PageSnapshot(
                "https://x.example/robots.txt", 200, "text/plain", "User-agent: *\nDisallow: /b"
            ),
            url_a: PageSnapshot(url_a, 403, "text/html", "Access Denied", "waf"),
            url_b: TimeoutError("boom"),
        }
    )
    rows, robots = probe(router, [url_a, url_b], today=TODAY)
    assert router.fetched == ["https://x.example/robots.txt", url_a, url_b]
    assert [(r.status, r.blocked_by) for r in rows] == [
        ("200", "none"),
        ("403", "waf"),
        ("error", "none"),
    ]
    assert rows[2].content_type == "TimeoutError"
    assert "Disallow: /b" in robots["x.example"]
    rows, _ = probe(FakeRouter(), [url_a], today=TODAY, robots=False)
    assert len(rows) == 1


def test_robots_url_only_for_http_urls():
    assert robots_url("https://a.example/x/y?z=1") == "https://a.example/robots.txt"
    assert robots_url("ftp://a.example/x") is None
    assert robots_url("not a url") is None


def test_probe_rows_are_appended_once(tmp_path):
    dossier = new_dossier(tmp_path)
    row = ProbeRow(TODAY, "https://x.example/a|b", "200", "text/html", "none")
    assert append_rows(dossier / "discovery.md", [row]) == 1
    assert append_rows(dossier / "discovery.md", [row]) == 0
    text = (dossier / "discovery.md").read_text()
    assert text.count("https://x.example/a/b") == 1
    assert text.index("https://x.example/a/b") < text.index("## Structure found")


# --- CLI ------------------------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "INGESTIONS_DIR", tmp_path)
    for name in cli.AGENT_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_cli_probe_writes_evidence_and_dry_run_does_not(repo, monkeypatch, capsys):
    dossier = new_dossier(repo)
    router = FakeRouter()
    monkeypatch.setattr(cli, "make_router", lambda: router)
    assert (
        cli.main(["probe", "--id", "acme_grants", "--url", "https://a.example/x", "--dry-run"]) == 0
    )
    assert "| 200 |" in capsys.readouterr().out
    assert "https://a.example" not in (dossier / "discovery.md").read_text()
    assert cli.main(["probe", "--id", "acme_grants", "--url", "https://a.example/x"]) == 0
    assert router.closed and (dossier / "discovery.md").read_text().count("https://a.example") == 2


def test_cli_probe_without_obscura_fails_cleanly(repo, monkeypatch, capsys):
    new_dossier(repo)

    def no_router():
        raise RuntimeError("obscura.sh is mandatory")

    monkeypatch.setattr(cli, "make_router", no_router)
    assert cli.main(["probe", "--id", "acme_grants", "--url", "https://a.example"]) == 1
    assert "obscura.sh is mandatory" in capsys.readouterr().err


def test_cli_status_advance_review_follow_the_workflow(repo, capsys):
    dossier = new_dossier(repo)
    assert cli.main(["status", "--id", "acme_grants"]) == 1
    assert "missing: discovery.md" in capsys.readouterr().out
    assert cli.main(["advance", "--id", "acme_grants"]) == 1
    fill_discovery(dossier)
    assert cli.main(["status", "--id", "acme_grants"]) == 0
    assert "ready: `make advance" in capsys.readouterr().out
    assert cli.main(["advance", "--id", "acme_grants"]) == 0
    assert load_dossier(dossier).state["phase"] == "assessment"
    assert cli.main(["review", "--id", "acme_grants"]) == 1  # blueprint still has TODOs
    assert cli.main(["status", "--id", "nope"]) == 1


def test_cli_sign_refuses_agents_and_non_interactive_shells(repo, monkeypatch, capsys):
    dossier = new_dossier(repo)
    fill_discovery(dossier)
    cli.main(["advance", "--id", "acme_grants"])
    fill_assessment(dossier)
    args = ["sign", "--id", "acme_grants", "--gate", "h1", "--by", "Ana Torres"]

    assert cli.main(args) == 1  # pytest's stdin is not a terminal
    assert "interactive terminal" in capsys.readouterr().err

    terminal = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr(cli.sys, "stdin", terminal)
    for variable in cli.AGENT_ENVIRONMENT:
        monkeypatch.setenv(variable, "1")
        assert cli.main(args) == 1
        assert "agent shell" in capsys.readouterr().err
        monkeypatch.delenv(variable)

    monkeypatch.setattr("builtins.input", lambda _: "nope")
    assert cli.main(args) == 1
    assert load_dossier(dossier).state["gates"]["h1"]["status"] == "pending"

    monkeypatch.setattr("builtins.input", lambda _: "h1")
    assert cli.main(args) == 0
    assert load_dossier(dossier).state["gates"]["h1"]["approved_by"] == "Ana Torres"
    monkeypatch.setattr(sys, "stdin", sys.__stdin__)


def test_check_contracts_also_validates_dossier_contract_folders(repo, monkeypatch, capsys):
    dossier = new_dossier(repo)
    (dossier / "contracts").mkdir()
    (dossier / "contracts" / "bad.yml").write_text("source_system: x\n")
    monkeypatch.setattr(cli, "iter_contract_files", lambda: iter(()))
    assert cli.main(["check-contracts"]) == 1
    assert "bad.yml" in capsys.readouterr().err
