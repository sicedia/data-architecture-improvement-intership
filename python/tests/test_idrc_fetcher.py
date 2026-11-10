"""PoliteFetcher: robots.txt, crawl-delay, request budget, host allow-list, stop conditions."""

from __future__ import annotations

import pytest
from scrapagents.extractors.idrc.fetcher import IdrcBlockedError, IdrcFetchError, PoliteFetcher
from scrapagents.stealth.base import PageSnapshot

BASE = "https://idrc-crdi.ca"
UA = "ScrapAgents-ingest-idrc/0.1 (research; non-commercial)"
ROBOTS = b"User-agent: *\ncrawl-delay: 5\nDisallow: /search/\n"


class FakeRouter:
    def __init__(self, pages: dict[str, PageSnapshot]) -> None:
        self.pages = pages
        self.requested: list[str] = []
        self.closed = False

    def fetch(self, url: str, *, timeout_seconds: float = 30.0) -> PageSnapshot:
        self.requested.append(url)
        return self.pages[url]

    def close(self) -> None:
        self.closed = True


class Clock:
    """Deterministic time: ``sleep`` advances it, so the spacing is observable."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _page(path: str, status: int = 200, body: bytes = b"<p>ok</p>") -> tuple[str, PageSnapshot]:
    url = f"{BASE}{path}"
    return url, PageSnapshot(url, status, "text/html", body.decode(), None, body)


def _fetcher(pages: dict[str, PageSnapshot], *, max_requests: int = 10, min_seconds: float = 5.0):
    router = FakeRouter(pages)
    clock = Clock()
    fetcher = PoliteFetcher(
        router,
        base_url=BASE,
        user_agent=UA,
        min_seconds_between_requests=min_seconds,
        max_requests=max_requests,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    return fetcher, router, clock


def _site(**extra: PageSnapshot) -> dict[str, PageSnapshot]:
    pages = dict([_page("/robots.txt", body=ROBOTS), _page("/en/funding"), _page("/en/funding/a")])
    pages.update(extra)
    return pages


def test_reads_robots_first_and_spaces_every_request_by_the_crawl_delay() -> None:
    fetcher, router, clock = _fetcher(_site())
    fetcher.fetch("/en/funding")
    fetcher.fetch("/en/funding/a")
    assert router.requested == [f"{BASE}/robots.txt", f"{BASE}/en/funding", f"{BASE}/en/funding/a"]
    assert clock.slept == [5.0, 5.0]
    assert fetcher.requests_made == 3


def test_robots_crawl_delay_wins_when_slower_than_the_configured_spacing() -> None:
    fetcher, _, clock = _fetcher(_site(), min_seconds=1.0)
    fetcher.fetch("/en/funding")
    assert fetcher.crawl_delay_seconds == 5.0
    assert clock.slept == [5.0]  # robots.txt is read first, so the page already waits 5 s


def test_a_path_disallowed_by_robots_is_not_requested() -> None:
    fetcher, router, _ = _fetcher(_site())
    with pytest.raises(IdrcFetchError, match="disallows"):
        fetcher.fetch("/search/anything")
    assert router.requested == [f"{BASE}/robots.txt"]


def test_missing_robots_means_no_rules() -> None:
    pages = _site()
    url, page = _page("/robots.txt", status=404, body=b"")
    pages[url] = page
    fetcher, _, _ = _fetcher(pages)
    assert fetcher.fetch("/en/funding").status == 200
    assert fetcher.crawl_delay_seconds == 5.0  # configured spacing still applies


def test_forbidden_robots_is_a_block() -> None:
    pages = _site()
    url, page = _page("/robots.txt", status=403, body=b"403 Forbidden")
    pages[url] = page
    fetcher, _, _ = _fetcher(pages)
    with pytest.raises(IdrcBlockedError):
        fetcher.fetch("/en/funding")


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (403, b"403 Forbidden", IdrcBlockedError),
        (200, b"<div class='g-recaptcha'></div>", IdrcBlockedError),
        (500, b"error", IdrcFetchError),
        (404, b"missing", IdrcFetchError),
    ],
)
def test_blocks_and_errors_stop_the_run(status: int, body: bytes, error: type[Exception]) -> None:
    url, page = _page("/en/funding", status=status, body=body)
    fetcher, _, _ = _fetcher(_site(**{url: page}))
    with pytest.raises(error):
        fetcher.fetch("/en/funding")


def test_request_budget_is_enforced() -> None:
    fetcher, _, _ = _fetcher(_site(), max_requests=2)
    fetcher.fetch("/en/funding")  # robots + page = 2 requests
    with pytest.raises(IdrcFetchError, match="budget"):
        fetcher.fetch("/en/funding/a")


def test_another_host_is_refused() -> None:
    fetcher, router, _ = _fetcher(_site())
    with pytest.raises(IdrcFetchError, match="outside the source host"):
        fetcher.fetch("https://example.org/en/funding")
    assert router.requested == [f"{BASE}/robots.txt"]


def test_close_closes_the_router() -> None:
    fetcher, router, _ = _fetcher(_site())
    fetcher.close()
    assert router.closed
