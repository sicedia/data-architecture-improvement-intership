"""``HttpRuntimeClient`` against a throw-away local HTTP server (no Rust binary needed)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from scrapagents.extractors.fixture import FixtureExtractor, dataset_name
from scrapagents.runtime_client import HttpRuntimeClient, RuntimeIngestError


class _Handler(BaseHTTPRequestHandler):
    received: list[dict] = []
    fail = False

    def log_message(self, *args):  # silence
        pass

    def _read_chunked(self) -> bytes:
        body = b""
        while True:
            size = int(self.rfile.readline().strip(), 16)
            if size == 0:
                self.rfile.readline()
                return body
            body += self.rfile.read(size)
            self.rfile.readline()

    def _send(self, status: int, payload: dict | str):
        data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, "ok")

    def do_POST(self):
        body = self._read_chunked()
        if _Handler.fail:
            return self._send(502, {"error": "tika down"})
        _Handler.received.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        self._send(
            200,
            {
                "source_id": self.path.split("/")[3],
                "dataset": self.path.split("/")[4],
                "sha256": "ab" * 32,
                "size_bytes": len(body),
                "object_key": "source=x/dataset=y/dt=2026-11-09/sha256=" + "ab" * 32,
                "route": "bronze",
                "text_key": None,
            },
        )


@pytest.fixture
def server():
    _Handler.received = []
    _Handler.fail = False
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_streams_chunks_and_sends_hints(server):
    client = HttpRuntimeClient(server)
    assert client.healthy()
    receipt = client.ingest(
        "demo",
        "records",
        iter([b'{"a":', b"1}"]),
        content_type="application/json",
        filename="r.json",
        ingest_date="2026-11-09",
    )
    sent = _Handler.received[0]
    assert sent["path"] == "/v1/ingest/demo/records"
    assert sent["body"] == b'{"a":1}'
    assert sent["headers"]["X-Ingest-Date"] == "2026-11-09"
    assert sent["headers"]["X-Filename"] == "r.json"
    assert receipt.route == "bronze" and receipt.size_bytes == 7


def test_runtime_errors_are_raised(server):
    _Handler.fail = True
    with pytest.raises(RuntimeIngestError, match="502.*tika down"):
        HttpRuntimeClient(server).ingest("demo", "records", [b"x"], ingest_date="2026-11-09")


def test_unreachable_runtime_is_not_healthy():
    assert not HttpRuntimeClient("http://127.0.0.1:1").healthy()


def test_only_http_urls_are_accepted():
    with pytest.raises(ValueError):
        HttpRuntimeClient("https://example.org")


def test_fixture_extractor_streams_every_file(server, tmp_path: Path):
    (tmp_path / "My Data.JSON").write_bytes(b"{}")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01")
    receipts = FixtureExtractor(HttpRuntimeClient(server), tmp_path).run("2026-11-09")
    assert set(receipts) == {"My Data.JSON", "blob.bin"}
    assert {r["path"] for r in _Handler.received} == {
        "/v1/ingest/fixture/my_data",
        "/v1/ingest/fixture/blob",
    }
    assert dataset_name(Path("Ünï cödé.csv")) == "n_c_d"
