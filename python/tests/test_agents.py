"""F5: the agent definitions are well formed and only refer to commands that exist."""

import re

import pytest
import yaml
from scrapagents.cli import build_parser
from scrapagents.paths import REPO_ROOT

AGENTS = ("source-scout", "source-assessor", "silver-designer", "arch-reviewer")
AGENT_DIR = REPO_ROOT / ".claude" / "agents"
SKILL = REPO_ROOT / ".claude" / "skills" / "new-source" / "SKILL.md"
DOCS = [AGENT_DIR / f"{name}.md" for name in AGENTS] + [SKILL]


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{path.name} has no frontmatter"
    return yaml.safe_load(match.group(1)), text[match.end() :]


@pytest.mark.parametrize("name", AGENTS)
def test_agents_are_defined_with_matching_names(name):
    meta, body = frontmatter(AGENT_DIR / f"{name}.md")
    assert meta["name"] == name
    assert len(meta["description"]) > 40
    assert body.strip()


def test_the_skill_is_manual_only():
    meta, _ = frontmatter(SKILL)
    assert meta["name"] == "new-source" and meta["disable-model-invocation"] is True


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.stem)
def test_every_agent_forbids_signing_and_editing_the_state(path):
    text = path.read_text(encoding="utf-8")
    assert "state.yml" in text
    assert re.search(r"[Nn]ever (sign|edit `state.yml`|run `make sign`)", text)


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.stem)
def test_documents_only_use_existing_make_targets_and_cli_commands(path):
    text = path.read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"^([a-z][\w-]*):", makefile, re.MULTILINE))
    for target in re.findall(r"`?make ([a-z][\w-]*)", text):
        assert target in targets, f"{path.name}: make {target} does not exist"
    commands = set(build_parser()._subparsers._group_actions[0].choices)
    for command in re.findall(r"scrapagents\.cli ([a-z][\w-]*)", text):
        assert command in commands, f"{path.name}: scrapagents {command} does not exist"


def test_only_humans_sign_and_the_reviewer_is_read_only():
    reviewer = (AGENT_DIR / "arch-reviewer.md").read_text(encoding="utf-8")
    assert "Read-only on the design" in reviewer
    for name in AGENTS:
        text = (AGENT_DIR / f"{name}.md").read_text(encoding="utf-8")
        assert "make sign ID=<id> GATE=h2" not in text  # agents never tell themselves to sign


def test_agent_definitions_are_design_time_only():
    """Invariant 1: prompts live under .claude/ and .cursor/, never in a run-time directory."""
    for runtime_dir in ("dags", "dbt", "rust", "infra"):
        found = [
            p for p in (REPO_ROOT / runtime_dir).rglob("*") if p.name in {f"{a}.md" for a in AGENTS}
        ]
        assert found == []
