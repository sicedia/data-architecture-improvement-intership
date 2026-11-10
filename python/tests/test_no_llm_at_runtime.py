"""Invariant 1: no LLM SDK may be imported by code that runs in production.

Run-time code is: ingestion extractors, DAGs, dbt Python, and the ``scrapagents`` library
itself. Design-time agents are prompts and rules, not Python imported by those paths.
"""

from pathlib import Path

from scrapagents.invariants import LLM_MODULES, imported_modules, is_llm_module
from scrapagents.paths import REPO_ROOT

FORBIDDEN = LLM_MODULES
RUNTIME_DIRS = ("ingestions", "dags", "dbt", "python/scrapagents")


def _runtime_python_files() -> list[Path]:
    files: list[Path] = []
    for rel in RUNTIME_DIRS:
        base = REPO_ROOT / rel
        if base.is_dir():
            files.extend(p for p in base.rglob("*.py") if "_template" not in p.parts)
    return files


def _is_forbidden(module: str) -> bool:
    return is_llm_module(module)


def test_runtime_code_does_not_import_llm_sdks():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {module}"
        for path in _runtime_python_files()
        for module in imported_modules(path.read_text(encoding="utf-8"))
        if _is_forbidden(module)
    ]
    assert offenders == []


def test_guard_detects_an_llm_import():
    bad = imported_modules("import openai\nfrom anthropic import X")
    good = imported_modules("import yaml\nfrom pathlib import Path")
    assert any(_is_forbidden(m) for m in bad)
    assert not any(_is_forbidden(m) for m in good)


def test_guard_scans_the_library():
    assert any("scrapagents" in p.parts for p in _runtime_python_files())


def test_generated_dags_are_declarative_and_free_of_llm_sdks():
    """DAGs are YAML: every `uses:` is an allowed operator and no LLM SDK is mentioned."""
    import re

    from scrapagents.dags import ALLOWED_OPERATORS

    dag_files = sorted((REPO_ROOT / "dags").glob("*.yml"))
    assert dag_files, "expected generated DAGs in dags/"
    for path in dag_files:
        text = path.read_text(encoding="utf-8")
        used = set(re.findall(r"^\s*uses:\s*(\S+)", text, flags=re.MULTILINE))
        assert used <= ALLOWED_OPERATORS, f"{path.name}: {used - ALLOWED_OPERATORS}"
        mentioned = [
            bad
            for bad in FORBIDDEN
            if re.search(rf"(?<![\w.]){re.escape(bad)}(?![\w])", text.lower())
        ]
        assert mentioned == [], f"{path.name} mentions {mentioned}"


def test_dbt_project_is_free_of_llm_sdks():
    """dbt models and macros are SQL/Jinja: no LLM SDK or prompt machinery may appear in them."""
    import re

    files = [p for p in (REPO_ROOT / "dbt").rglob("*") if p.suffix in {".sql", ".yml", ".txt"}]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        mentioned = [
            bad for bad in FORBIDDEN if re.search(rf"(?<![\w.]){re.escape(bad)}(?![\w])", text)
        ]
        assert mentioned == [], f"{path.relative_to(REPO_ROOT)} mentions {mentioned}"
