"""Discovery probes: fetch URLs through a ``StealthRouter`` and record the evidence in the dossier.

Invariant 3: a browser is only ever reached through ``scrapagents.stealth`` (playwright paired with
obscura.sh). The router is injected, so tests and the CLI share this code without a real browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from scrapagents.stealth.base import StealthRouter


@dataclass(frozen=True)
class ProbeRow:
    date: str
    url: str
    status: str  # three digits, or "error" when the browser got no answer
    content_type: str
    blocked_by: str  # "none", "captcha" or "waf"

    def markdown(self) -> str:
        cells = (self.date, self.url, self.status, self.content_type, self.blocked_by)
        return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |"


def robots_url(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def probe(
    router: StealthRouter,
    urls: list[str],
    *,
    today: str,
    robots: bool = True,
    timeout_seconds: float = 30.0,
) -> tuple[list[ProbeRow], dict[str, str]]:
    """One row per URL (plus one per host for ``robots.txt``) and the robots.txt text per host."""

    targets: list[str] = []
    for url in urls:
        if robots and (robots_txt := robots_url(url)) and robots_txt not in targets:
            targets.append(robots_txt)
        if url not in targets:
            targets.append(url)
    rows: list[ProbeRow] = []
    robots_text: dict[str, str] = {}
    for url in targets:
        try:
            page = router.fetch(url, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - a failed fetch is evidence, not a crash
            rows.append(ProbeRow(today, url, "error", type(exc).__name__, "none"))
            continue
        status = str(page.status) if page.status else "error"
        content_type = (page.content_type or "unknown").split(";")[0].strip()
        rows.append(ProbeRow(today, url, status, content_type, page.blocked_by or "none"))
        if url.endswith("/robots.txt"):
            robots_text[urlsplit(url).netloc] = page.html
    return rows, robots_text


def append_rows(discovery: Path, rows: list[ProbeRow]) -> int:
    """Add the rows under the probe table of ``discovery.md``; returns how many were new."""

    lines = discovery.read_text(encoding="utf-8").splitlines()
    header = next((i for i, line in enumerate(lines) if line.strip().startswith("| Date")), None)
    if header is None:
        raise ValueError("discovery.md has no probe table (header starting with '| Date')")
    end = header + 2  # header and separator
    while end < len(lines) and lines[end].strip().startswith("|"):
        end += 1
    existing = {line.strip() for line in lines[header + 2 : end]}
    new = [row.markdown() for row in rows if row.markdown() not in existing]
    lines[end:end] = new
    discovery.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(new)
