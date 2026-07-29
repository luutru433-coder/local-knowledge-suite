# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from local_knowledge.ckb.config import Settings
from local_knowledge.ckb.lmstudio import LMStudioClient
from local_knowledge.ckb.models import ParsedSection


class LMHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = {"data": [{"id": "chat"}, {"id": "embed"}]}
        self._json(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith("/embeddings"):
            inputs = body.get("input", [])
            self._json({"data": [{"index": index, "embedding": [float(index + 1), 2.0]} for index, _ in enumerate(inputs)]})
        else:
            content = json.dumps({"claims": [{"text": "Revenue is weekly.", "confidence": 0.95, "section_index": 0, "excerpt": "Revenue is weekly."}]})
            self._json({"choices": [{"message": {"content": content}}]})

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        return


def test_lm_studio_health_extraction_and_embeddings_ignore_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LMHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        client = LMStudioClient(f"http://127.0.0.1:{server.server_address[1]}/v1", "chat", "embed")
        health = client.health()
        claims = client.extract_claims("Revenue", "en", [ParsedSection("line 1", "Policy", "Revenue is weekly.")])
        vectors = client.embed(["one", "two"])
    finally:
        server.shutdown()
        thread.join(timeout=2)
    assert health["chat_endpoint"] is True
    assert health["embedding_endpoint"] is True
    assert claims[0]["text"] == "Revenue is weekly."
    assert vectors == [[1.0, 2.0], [2.0, 2.0]]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1:1234/v1",
        "http://user:password@127.0.0.1:1234/v1",
        "http://127.0.0.1:1234/v1?target=remote",
        "http://127.0.0.1:1234/v1#fragment",
        "http://10.0.0.4:1234/v1",
        "http://192.168.1.50:1234/v1",
        "https://8.8.8.8/v1",
        "http://lm.example.test:1234/v1",
        "http://localhost.example.test:1234/v1",
        " http://127.0.0.1:1234/v1",
        "http://127.0.0.1:1234/v1 bad",
        "http://127.0.0.1:/v1",
    ],
)
def test_lm_studio_client_rejects_non_loopback_urls_before_network(
    url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "local_knowledge.ckb.lmstudio.httpx.Client",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("network client must not be created")
        ),
    )
    with pytest.raises(ValueError, match="LM Studio"):
        LMStudioClient(url, "chat", "embed")


def test_settings_reject_remote_env_config_and_direct_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "company"
    config = root / ".ckb" / "config.json"
    config.parent.mkdir(parents=True)
    monkeypatch.setenv("CKB_LM_STUDIO_URL", "http://203.0.113.10:1234/v1")
    with pytest.raises(ValueError, match="loopback"):
        Settings.load(root)

    monkeypatch.delenv("CKB_LM_STUDIO_URL")
    config.write_text(
        json.dumps({"lm_studio_url": "http://10.0.0.8:1234/v1"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="loopback"):
        Settings.load(root)

    with pytest.raises(ValueError, match="loopback"):
        Settings(
            root=root,
            data_dir=root / ".ckb",
            database=root / ".ckb" / "ckb.sqlite3",
            bundle_dir=root / "knowledge",
            lm_studio_url="https://public.example/v1",
        )


def test_localhost_lm_studio_url_is_canonicalized_to_numeric_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "company"
    root.mkdir()
    monkeypatch.setenv(
        "CKB_LM_STUDIO_URL",
        "HTTP://LOCALHOST:1234/v1/",
    )
    settings = Settings.load(root)
    client = LMStudioClient(
        "https://LOCALHOST:4321/v1/",
        "chat",
        "embed",
    )

    assert settings.lm_studio_url == "http://127.0.0.1:1234/v1"
    assert client.base_url == "https://127.0.0.1:4321/v1"
    assert (
        LMStudioClient("http://[::1]:1234/v1/", "chat", "embed").base_url
        == "http://[::1]:1234/v1"
    )


def test_private_crawl_escape_hatch_is_not_a_runtime_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "company"
    config = root / ".ckb" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"crawler_allow_private_hosts": True}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CKB_ALLOW_PRIVATE_CRAWL", "true")

    settings = Settings.load(root)
    written = json.loads(settings.write_user_config().read_text(encoding="utf-8"))

    assert not hasattr(settings, "crawler_allow_private_hosts")
    assert "crawler_allow_private_hosts" not in written


def test_cors_is_process_local_opt_in_and_old_persisted_defaults_are_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "company"
    config = root / ".ckb" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "cors_origins": [
                    "http://localhost:5173",
                    "http://127.0.0.1:5173",
                ]
            }
        ),
        encoding="utf-8",
    )

    settings = Settings.load(root)
    assert settings.cors_origins == ()
    assert "cors_origins" not in json.loads(
        settings.write_user_config().read_text(encoding="utf-8")
    )

    monkeypatch.setenv("CKB_CORS_ORIGINS", "https://attacker.example")
    with pytest.raises(ValueError, match="loopback"):
        Settings.load(root)

    monkeypatch.setenv(
        "CKB_CORS_ORIGINS",
        "http://localhost:5173,http://127.99.1.2:4173/",
    )
    opted_in = Settings.load(root)
    assert opted_in.cors_origins == (
        "http://localhost:5173",
        "http://127.99.1.2:4173",
    )
    assert "cors_origins" not in json.loads(
        opted_in.write_user_config().read_text(encoding="utf-8")
    )
