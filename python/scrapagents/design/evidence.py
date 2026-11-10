"""Is the Markdown evidence of a phase complete? Deterministic checks, no judgement.

The agents write ``discovery.md`` and ``assessment.md``; these checks tell them (and the human who
signs Gate H1) what is still missing, and refuse an assessment that contradicts invariant 4.
"""

from __future__ import annotations

import re

from scrapagents.design.markdown import bullets, is_filled, lookup, table_rows
from scrapagents.invariants import PLAIN_FORMATS, TIKA_FORMATS

DISCOVERY_FIELDS = (
    "Institution / portal URL",
    "Access type",
    "robots.txt and Terms of Service",
    "Endpoints or DOM entry points",
    "Pagination and ordering",
    "Authentication",
    "Payload formats",
    "Estimated volume and change rate",
)
ASSESSMENT_FIELDS = (
    "Legal / ToS risk",
    "Anti-bot risk and mitigation",
    "Personal data",
    "Duplicates an existing CEDIA source",
    "Full scope per run or incremental",
    "Proposed schedule and why",
    "Decision",
    "Reason",
)
BLOCKS = frozenset({"none", "captcha", "waf"})
FORMATS = PLAIN_FORMATS | TIKA_FORMATS
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATUS = re.compile(r"^(\d{3}|error)$")


def _missing_fields(text: str, fields: tuple[str, ...], where: str) -> list[str]:
    found = bullets(text)
    return [
        f"{where}: '- {field}:' is empty" for field in fields if not is_filled(lookup(found, field))
    ]


def discovery_issues(text: str) -> list[str]:
    issues = _missing_fields(text, DISCOVERY_FIELDS, "discovery.md")
    rows = table_rows(text, "| Date")
    if not rows:
        issues.append("discovery.md: no probe evidence (run `make probe ID=<id> URL=<url>`)")
    reachable = False
    for number, row in enumerate(rows, start=1):
        if len(row) != 5:
            issues.append(f"discovery.md: probe row {number} must have 5 columns")
            continue
        date, url, status, _content_type, blocked = row
        if not _DATE.match(date):
            issues.append(f"discovery.md: probe row {number} has a bad date {date!r}")
        if not url.startswith(("http://", "https://")):
            issues.append(f"discovery.md: probe row {number} has a bad URL {url!r}")
        if not _STATUS.match(status):
            issues.append(f"discovery.md: probe row {number} has a bad status {status!r}")
        elif status != "error":
            reachable = True
        if blocked.lower() not in BLOCKS:
            issues.append(f"discovery.md: probe row {number} 'Blocked by' must be {sorted(BLOCKS)}")
    if rows and not reachable:
        issues.append("discovery.md: no probe got an HTTP answer")
    return issues


def decision(text: str) -> str | None:
    value = lookup(bullets(text), "Decision")
    return value.strip().lower() if is_filled(value) else None


def payload_formats(text: str) -> set[str]:
    """Formats listed in the payload triage table."""

    return {row[1].strip().lower() for row in table_rows(text, "| Payload") if len(row) >= 2}


def assessment_issues(text: str) -> list[str]:
    issues = _missing_fields(text, ASSESSMENT_FIELDS, "assessment.md")
    found = bullets(text)
    for field in ("Personal data", "Duplicates an existing CEDIA source"):
        value = lookup(found, field)
        if is_filled(value) and not value.lower().startswith(("yes", "no")):
            issues.append(f"assessment.md: '{field}' must start with yes or no")
    answer = decision(text)
    if answer is not None and answer not in {"go", "no-go"}:
        issues.append("assessment.md: Decision must be 'go' or 'no-go'")

    rows = table_rows(text, "| Payload")
    if not rows:
        issues.append("assessment.md: the payload triage table has no rows")
    for number, row in enumerate(rows, start=1):
        if len(row) != 3:
            issues.append(f"assessment.md: payload row {number} must have 3 columns")
            continue
        payload, fmt, tika = row[0], row[1].lower(), row[2].lower()
        if fmt not in FORMATS:
            issues.append(
                f"assessment.md: payload {payload!r}: format must be one of {sorted(FORMATS)}"
            )
            continue
        wants_tika = fmt in TIKA_FORMATS
        if tika not in {"yes", "no"}:
            issues.append(f"assessment.md: payload {payload!r}: 'Goes to Tika?' must be yes or no")
        elif (tika == "yes") != wants_tika:
            rule = "must go to Tika" if wants_tika else "never goes to Tika"
            issues.append(f"assessment.md: payload {payload!r}: {fmt} {rule} (invariant 4)")
    return issues
