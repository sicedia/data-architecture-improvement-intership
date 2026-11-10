"""Facts about the architectural invariants that code and tests check against.

One definition, used by the no-LLM-at-run-time test and by the design-time reviewer.
"""

from __future__ import annotations

import ast

# Invariant 1: modules that must never be imported by production code.
LLM_MODULES = frozenset(
    {
        "openai",
        "anthropic",
        "langchain",
        "langchain_core",
        "langgraph",
        "litellm",
        "llama_index",
        "cohere",
        "mistralai",
        "ollama",
        "groq",
        "transformers",
        "claude_agent_sdk",
        "cursor_sdk",
        "google.generativeai",
        "google.genai",
    }
)

# Invariant 4: only these complex binaries go through Apache Tika; JSON, XML, HTML and CSV never do.
TIKA_FORMATS = frozenset({"pdf", "docx"})
PLAIN_FORMATS = frozenset({"json", "xml", "html", "csv"})


def is_llm_module(module: str) -> bool:
    return any(module == bad or module.startswith(bad + ".") for bad in LLM_MODULES)


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules
