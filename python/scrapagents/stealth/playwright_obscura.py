"""``StealthRouter`` backed by playwright (sync API) and ``ObscuraConfig``."""

from __future__ import annotations

from types import TracebackType
from typing import Any

from scrapagents.stealth.base import ObscuraConfig, PageSnapshot

CAPTCHA_MARKERS = ("g-recaptcha", "h-captcha", "cf-turnstile", "captcha-delivery")
WAF_MARKERS = ("just a moment...", "attention required", "access denied", "request unsuccessful")


def detect_block(status: int | None, html: str) -> str | None:
    """Classify an anti-bot barrier from the response, or ``None`` when the page looks open."""

    lowered = html.lower()
    if any(marker in lowered for marker in CAPTCHA_MARKERS):
        return "captcha"
    if status in (403, 429) or any(marker in lowered for marker in WAF_MARKERS):
        return "waf"
    return None


class PlaywrightObscuraRouter:
    """Playwright connected to Obscura over CDP. playwright is imported lazily.

    With ``OBSCURA_CDP_URL`` the browser is the remote Obscura instance and is never closed by us
    (only the pages and the connection). Without it (``OBSCURA_REQUIRED=0``, local development) a
    local Chromium is launched instead.
    """

    def __init__(self, config: ObscuraConfig | None = None) -> None:
        self._config = config or ObscuraConfig.from_env()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    def _start(self) -> Any:
        if self._context is not None:
            return self._context
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise RuntimeError("playwright is missing: pip install '.[probes]'") from exc
        self._playwright = sync_playwright().start()
        if self._config.cdp_url:
            headers = (
                {"Authorization": f"Bearer {self._config.cdp_token}"}
                if self._config.cdp_token
                else None
            )
            self._browser = self._playwright.chromium.connect_over_cdp(
                self._config.cdp_url, headers=headers
            )
        else:  # local development only (OBSCURA_REQUIRED=0)
            self._browser = self._playwright.chromium.launch(headless=True)
        # Sites with incomplete or corporate TLS chains (e.g. CAF) fail navigation unless TLS
        # errors are ignored at the browser context. Recorded for H1; never a bypass of WAF/captcha.
        context_args: dict[str, Any] = {"ignore_https_errors": True}
        if self._config.user_agent:
            context_args["user_agent"] = self._config.user_agent
        self._context = self._browser.new_context(**context_args)
        return self._context

    def fetch(self, url: str, *, timeout_seconds: float = 30.0) -> PageSnapshot:
        page = self._start().new_page()
        try:
            response = page.goto(url, timeout=timeout_seconds * 1000, wait_until="domcontentloaded")
            status = response.status if response else None
            content_type = response.headers.get("content-type") if response else None
            html = page.content()
            body = response.body() if response else b""
            return PageSnapshot(url, status, content_type, html, detect_block(status, html), body)
        finally:
            page.close()

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()  # over CDP this disconnects; the remote Obscura keeps running
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._context = None

    def __enter__(self) -> PlaywrightObscuraRouter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
