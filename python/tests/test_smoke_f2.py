"""F2 end-to-end smoke: extractor -> RustWorker -> RustFS Landing / PostgreSQL bronze / Tika.

Needs `make infra-up` (stacks warehouse and ingestion; it also creates the typed bronze
tables) and `pip install -e ".[smoke]"`;
it is skipped when the runtime is not reachable. Env overrides: RUNTIME_URL, S3_URL,
RUSTFS_ACCESS_KEY, RUSTFS_SECRET_KEY, POSTGRES_CONTAINER.
"""

import os
import subprocess
from pathlib import Path

import pytest
from scrapagents.extractors.fixture import FixtureExtractor
from scrapagents.runtime_client import HttpRuntimeClient

FIXTURES = Path(__file__).parent / "fixtures"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@pytest.fixture(scope="module")
def client() -> HttpRuntimeClient:
    c = HttpRuntimeClient(_env("RUNTIME_URL", "http://127.0.0.1:8088"))
    if not c.healthy():
        pytest.skip("source_runtime is not running (make infra-up)")
    return c


def _psql(sql: str) -> str:
    container = _env("POSTGRES_CONTAINER", "")
    if not container:
        for name in ("scrapagents-postgres", "scrapagents-warehouse-postgres-1"):
            check = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", name],
                capture_output=True,
                text=True,
            )
            if check.returncode == 0 and check.stdout.strip() == "true":
                container = name
                break
        container = container or "scrapagents-postgres"
    out = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "scrapagents", "-d", "scrapagents",
         "-tA", "-c", sql],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return out.stdout.strip()


def test_fixture_source_end_to_end(client):
    boto3 = pytest.importorskip("boto3")
    # `fixture` is the registered source: its `records` dataset has the typed table
    # bronze.fixture__records. Loading the same payload twice adds nothing (same batch id).
    source = "fixture"
    receipts = FixtureExtractor(client, FIXTURES, source_id=source).run("2026-11-09")

    routes = {name: r.route for name, r in receipts.items()}
    assert routes == {
        "blob.bin": "quarantine",
        "page.html": "bronze",
        "records.json": "bronze",
        "sample.pdf": "tika",
        "table.csv": "bronze",
    }

    # The recorded hash is the real SHA-256 of what was streamed.
    import hashlib

    for name, receipt in receipts.items():
        assert receipt.sha256 == hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()

    s3 = boto3.client(
        "s3",
        endpoint_url=_env("S3_URL", "http://127.0.0.1:9000"),
        aws_access_key_id=_env("RUSTFS_ACCESS_KEY", "scrapagents"),
        aws_secret_access_key=_env("RUSTFS_SECRET_KEY", "change-me-local-only"),
        region_name="us-east-1",
    )
    keys = {
        o["Key"]
        for o in s3.list_objects_v2(Bucket="landing", Prefix=f"source={source}/")["Contents"]
    }
    # Every payload is in Landing; only the PDF has a Tika text next to it.
    assert {r.object_key for r in receipts.values()} <= keys
    text_key = receipts["sample.pdf"].text_key
    assert text_key in keys
    assert len([k for k in keys if k.endswith(".txt") and "dt=2026-11-09" in k]) == 1
    text = s3.get_object(Bucket="landing", Key=text_key)["Body"].read().decode()
    assert "Hello Tika fixture" in text

    # The records reached their typed table; CSV and HTML are landed only; the unknown binary
    # reached quarantine. Re-running the smoke is idempotent.
    assert receipts["records.json"].bronze_table == "fixture__records"
    assert receipts["records.json"].bronze_rows == 2
    assert receipts["table.csv"].bronze_table is None
    assert _psql("select count(*) from bronze.fixture__records") == "2"
    assert _psql("select payload->>'name' from bronze.fixture__records where id='1'") == "alpha"
    assert _psql(
        "select count(distinct _batch_id) || ',' || count(*) from bronze.fixture__records"
    ) == "1,2"
    assert _psql(
        "select count(*) from bronze.fixture__records "
        "where _landing_uri = 's3://landing/' || '" + receipts["records.json"].object_key + "'"
    ) == "2"
    assert _psql(
        "select count(*) from bronze_quarantine.rejected_payloads where source='fixture'"
    ) == "1"
