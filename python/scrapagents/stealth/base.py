"""Interface every browser-based probe or extractor depends on."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ObscuraConfig:
    """Where the Obscura browser lives.

    Obscura (``obscura.sh``) is a headless browser written in Rust and built for AI agents. It
    is the *destination* of the session: instead of opening a local Chromium on the extractor
    host, Playwright connects to Obscura over the Chrome DevTools Protocol
    (``connect_over_cdp``).

    * ``OBSCURA_CDP_URL``: CDP endpoint of the Obscura instance, for example ``ws://obscura:9222``
      or ``http://obscura:9222``.
    * ``OBSCURA_CDP_TOKEN``: bearer token. Obscura (image ``h4ckf0r0day/obscura:0.2.6``) refuses to
      serve CDP without a token of at least 32 bytes and answers 401 without it; it is sent in an
      ``Authorization: Bearer`` header, never in the URL.
    * ``OBSCURA_USER_AGENT``: optional user agent for the browser context.
    * ``OBSCURA_REQUIRED``: ``0`` lets a probe fall back to a local Chromium when no endpoint is
      set (local development only; never in production).
    """

    cdp_url: str | None = None
    cdp_token: str | None = None
    user_agent: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ObscuraConfig:
        values = os.environ if env is None else env
        config = cls(
            cdp_url=values.get("OBSCURA_CDP_URL") or None,
            cdp_token=values.get("OBSCURA_CDP_TOKEN") or None,
            user_agent=values.get("OBSCURA_USER_AGENT") or None,
        )
        if values.get("OBSCURA_REQUIRED", "1") != "0" and config.cdp_url is None:
            raise RuntimeError(
                "obscura.sh is mandatory for browser access (invariant 3): set OBSCURA_CDP_URL "
                "to the CDP endpoint of Obscura, or OBSCURA_REQUIRED=0 for local development."
            )
        return config

    @property
    def uses_obscura(self) -> bool:
        return self.cdp_url is not None


@dataclass(frozen=True)
class PageSnapshot:
    """What a probe records about one page; evidence for the Discovery phase."""

    url: str
    status: int | None
    content_type: str | None
    html: str
    blocked_by: str | None = None  # "captcha", "waf" or None
    # Original bytes of the HTTP response (not the rendered DOM), for extractors that must land
    # exactly what the source sent. Empty when the router could not read the body.
    body: bytes = b""


class StealthRouter(Protocol):
    """Fetches pages through a browser session on Obscura."""

    def fetch(self, url: str, *, timeout_seconds: float = 30.0) -> PageSnapshot: ...

    def close(self) -> None: ...
