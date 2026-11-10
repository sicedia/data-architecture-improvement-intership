"""Discovery helper for `idrc`: fetch a few URLs through the stealth router, keep the HTML locally.

Usage: OBSCURA_REQUIRED=0 .venv/bin/python ingestions/idrc/probes/fetch_html.py URL [URL ...]

Respects the robots.txt crawl-delay (5 s) between requests. HTML goes to `.cache/` (not committed)
so the structure can be inspected without re-requesting the page. Evidence rows are appended to
discovery.md.
"""

from __future__ import annotations

import datetime
import hashlib
import sys
import time
from pathlib import Path

from scrapagents.design.probes import append_rows, probe
from scrapagents.stealth import PlaywrightObscuraRouter

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
DELAY_SECONDS = 5.0


class _CachingRouter:
    def __init__(self, inner: PlaywrightObscuraRouter) -> None:
        self._inner = inner
        self._first = True

    def fetch(self, url: str, *, timeout_seconds: float = 30.0):
        if not self._first:
            time.sleep(DELAY_SECONDS)
        self._first = False
        page = self._inner.fetch(url, timeout_seconds=timeout_seconds)
        CACHE.mkdir(exist_ok=True)
        name = hashlib.sha1(url.encode()).hexdigest()[:10] + ".html"
        (CACHE / name).write_text(page.html, encoding="utf-8")
        print(f"{url} -> {CACHE / name} ({len(page.html)} chars)")
        return page

    def close(self) -> None:
        self._inner.close()


def main(urls: list[str]) -> int:
    with PlaywrightObscuraRouter() as inner:
        rows, _ = probe(
            _CachingRouter(inner),  # type: ignore[arg-type]
            urls,
            today=datetime.date.today().isoformat(),
            robots=False,
        )
    for row in rows:
        print(row.markdown())
    added = append_rows(HERE.parent / "discovery.md", rows)
    print(f"{added} new row(s) added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
