import hashlib

import pytest
from scrapagents.runtime_client import InMemoryRuntimeClient
from scrapagents.stealth.base import ObscuraConfig
from scrapagents.stealth.playwright_obscura import detect_block


def test_in_memory_client_hashes_like_the_runtime():
    client = InMemoryRuntimeClient()
    receipt = client.ingest("demo", "records", [b"hello ", b"world"])
    assert receipt.sha256 == hashlib.sha256(b"hello world").hexdigest()
    assert receipt.size_bytes == 11
    assert client.objects[receipt.object_key] == b"hello world"


def test_obscura_is_mandatory_unless_explicitly_disabled():
    with pytest.raises(RuntimeError):
        ObscuraConfig.from_env({})
    assert not ObscuraConfig.from_env({"OBSCURA_REQUIRED": "0"}).uses_obscura
    config = ObscuraConfig.from_env(
        {"OBSCURA_CDP_URL": "ws://obscura:9222", "OBSCURA_CDP_TOKEN": "t" * 32}
    )
    assert config.cdp_url == "ws://obscura:9222"
    assert config.cdp_token == "t" * 32
    assert config.uses_obscura


def test_detect_block():
    assert detect_block(200, "<div class='g-recaptcha'></div>") == "captcha"
    assert detect_block(403, "") == "waf"
    assert detect_block(200, "<title>Just a moment...</title>") == "waf"
    assert detect_block(200, "<p>ok</p>") is None
