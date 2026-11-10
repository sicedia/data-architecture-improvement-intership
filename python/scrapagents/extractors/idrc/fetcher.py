"""Read idrc-crdi.ca through the Obscura stealth router (source -> bytes in memory).

``PoliteFetcher`` is the only way this extractor reads the site. The site asks for politeness
(``robots.txt`` with ``crawl-delay: 5``) and its terms are silent about automated access, so every
request is checked and spaced here and nothing else may bypass it.

Stop conditions, recorded as errors and never worked around: a captcha or WAF page, a non-200
answer, a path ``robots.txt`` disallows, a host other than the source's, or more requests than the
configured budget.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from scrapagents.extractors.idrc.records import detect_block
from scrapagents.stealth.base import PageSnapshot, StealthRouter

logger = logging.getLogger(__name__)


class IdrcFetchError(RuntimeError):
    """A request failed or the site refused it; the run stops."""


class IdrcBlockedError(IdrcFetchError):
    """A captcha or WAF page, or a 403/429: recorded as a finding, never worked around."""


class PoliteFetcher:
    """robots.txt, crawl-delay, request budget, host allow-list and stop conditions."""

    def __init__(
        self,
        router: StealthRouter,
        *,
        base_url: str,
        user_agent: str,
        min_seconds_between_requests: float,
        max_requests: int,
        timeout_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._router = router
        self._base_url = base_url.rstrip("/")
        self._host = urlparse(self._base_url).netloc
        self._user_agent = user_agent
        self._min_seconds = float(min_seconds_between_requests)
        self._max_requests = int(max_requests)
        self._timeout = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self._requests = 0
        self._robots: RobotFileParser | None = None
        self.crawl_delay_seconds = self._min_seconds

    @property
    def requests_made(self) -> int:
        return self._requests

    def url(self, path: str) -> str:
        return urljoin(f"{self._base_url}/", path.lstrip("/"))

    def _wait_turn(self) -> None:
        if self._last_request_at is not None:
            remaining = self.crawl_delay_seconds - (self._monotonic() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)

    def _request(self, url: str) -> PageSnapshot:
        if urlparse(url).netloc != self._host:
            raise IdrcFetchError(f"{url} is outside the source host {self._host}.")
        if self._requests >= self._max_requests:
            raise IdrcFetchError(f"Request budget of {self._max_requests} per run exceeded.")
        self._wait_turn()
        self._requests += 1
        try:
            return self._router.fetch(url, timeout_seconds=self._timeout)
        finally:
            self._last_request_at = self._monotonic()

    def _load_robots(self) -> RobotFileParser:
        if self._robots is not None:
            return self._robots
        page = self._request(self.url("/robots.txt"))
        parser = RobotFileParser()
        if page.status == 200:
            parser.parse(page.body.decode("utf-8", errors="replace").splitlines())
        elif page.status in (401, 403, 429):
            raise IdrcBlockedError(
                f"robots.txt answered {page.status}: the site refuses automated access."
            )
        elif page.status in (404, 410):
            parser.parse([])  # no robots.txt means no rules
        else:
            raise IdrcFetchError(f"robots.txt answered {page.status}.")
        delay = parser.crawl_delay(self._user_agent) or parser.crawl_delay("*")
        if delay:
            self.crawl_delay_seconds = max(self._min_seconds, float(delay))
        self._robots = parser
        logger.info("idrc robots.txt loaded, crawl_delay=%ss", self.crawl_delay_seconds)
        return parser

    def fetch(self, path_or_url: str) -> PageSnapshot:
        """One page; fails on a disallowed path, a block or any answer other than 200."""

        robots = self._load_robots()
        url = path_or_url if path_or_url.startswith("http") else self.url(path_or_url)
        if not robots.can_fetch(self._user_agent, url):
            raise IdrcFetchError(f"robots.txt disallows {url}.")
        page = self._request(url)
        blocked = detect_block(page.status, page.body)
        if blocked:
            raise IdrcBlockedError(f"{url} answered {page.status} ({blocked}); the run stops.")
        if page.status != 200:
            raise IdrcFetchError(f"{url} answered {page.status}.")
        return page

    def close(self) -> None:
        self._router.close()
