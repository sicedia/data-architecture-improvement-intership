"""Contract between Python extractors and the Rust ``SourceRuntime`` / ``RustWorker``.

An extractor never hashes, stores or classifies payloads: it streams bytes and receives a
receipt. Hashing, triage (Tika only for complex binaries, before loading) and Landing writes
happen in Rust (``rust/source_runtime``). The real transport (F2) will implement
``SourceRuntimeClient``; until then ``InMemoryRuntimeClient`` lets extractor code be tested
without the binary.
"""

from __future__ import annotations

import hashlib
import http.client
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote, urlsplit


@dataclass(frozen=True)
class LandingReceipt:
    """What the runtime reports after it persisted one raw object."""

    source_id: str
    dataset: str
    sha256: str
    size_bytes: int
    object_key: str
    route: str | None = None  # "bronze", "tika" or "quarantine" (set by the Rust runtime)
    text_key: str | None = None  # Tika text object, only for complex binaries
    bronze_table: str | None = None  # typed bronze table the records were loaded into, if any
    bronze_rows: int | None = None  # records the payload held for that table


class RuntimeIngestError(RuntimeError):
    """The runtime refused or failed to ingest a payload."""


def today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def landing_key(source_id: str, dataset: str, ingest_date: str, sha256: str) -> str:
    """Hive-style key; identical to ``source_runtime::runtime::landing_key``."""
    return f"source={source_id}/dataset={dataset}/dt={ingest_date}/sha256={sha256}"


class SourceRuntimeClient(Protocol):
    def ingest(
        self,
        source_id: str,
        dataset: str,
        chunks: Iterable[bytes],
        *,
        content_type: str | None = None,
        filename: str | None = None,
        ingest_date: str | None = None,
    ) -> LandingReceipt:
        """Stream one payload to the runtime and return its receipt.

        ``ingest_date`` (YYYY-MM-DD) is the Landing partition; the caller picks it so the runtime
        stays deterministic. It defaults to today (UTC).
        """
        ...


class InMemoryRuntimeClient:
    """Test double: keeps payloads in memory and computes the same SHA-256 as the runtime."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def ingest(
        self,
        source_id: str,
        dataset: str,
        chunks: Iterable[bytes],
        *,
        content_type: str | None = None,
        filename: str | None = None,
        ingest_date: str | None = None,
    ) -> LandingReceipt:
        digest = hashlib.sha256()
        buffer = bytearray()
        for chunk in chunks:
            digest.update(chunk)
            buffer.extend(chunk)
        sha = digest.hexdigest()
        key = landing_key(source_id, dataset, ingest_date or today_utc(), sha)
        self.objects[key] = bytes(buffer)
        return LandingReceipt(source_id, dataset, sha, len(buffer), key)


class HttpRuntimeClient:
    """Streams payloads to the Rust ``source_runtime`` service (``POST /v1/ingest/...``).

    The body goes out with chunked transfer encoding, so extractors never hold the whole payload
    in memory on the Python side. Only the standard library is used.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8088", *, timeout: float = 120.0) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or not parts.hostname:
            raise ValueError(f"unsupported runtime url: {base_url!r} (expected http://host:port)")
        self._host = parts.hostname
        self._port = parts.port or 80
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: Iterable[bytes] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {}, encode_chunked=True)
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def healthy(self) -> bool:
        try:
            status, _ = self._request("GET", "/healthz")
        except OSError:
            return False
        return status == 200

    def ingest(
        self,
        source_id: str,
        dataset: str,
        chunks: Iterable[bytes],
        *,
        content_type: str | None = None,
        filename: str | None = None,
        ingest_date: str | None = None,
    ) -> LandingReceipt:
        headers = {"X-Ingest-Date": ingest_date or today_utc()}
        if content_type:
            headers["Content-Type"] = content_type
        if filename:
            headers["X-Filename"] = filename
        path = f"/v1/ingest/{quote(source_id, safe='')}/{quote(dataset, safe='')}"
        status, raw = self._request("POST", path, body=chunks, headers=headers)
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        if status != 200:
            raise RuntimeIngestError(f"runtime answered {status}: {data.get('error', raw[:200])}")
        return LandingReceipt(
            source_id=data["source_id"],
            dataset=data["dataset"],
            sha256=data["sha256"],
            size_bytes=data["size_bytes"],
            object_key=data["object_key"],
            route=data["route"],
            text_key=data.get("text_key"),
            bronze_table=data.get("bronze_table"),
            bronze_rows=data.get("bronze_rows"),
        )
