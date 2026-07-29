# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest


from local_knowledge.memorizer.core import (
    MemorizerError,
    Note,
    backlinks,
    capture,
    distill,
    graph,
    init_vault,
    link,
    load_notes,
    pin,
    rebuild_index,
    search,
    show,
    status,
    touch,
    validate_vault,
    vault_lock,
    vault_path,
    write_note,
)
import local_knowledge.memorizer.core as memorizer_core


def event(text: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "project-knowledge",
        "title": text[:60],
        "text": text,
        "memory_key": f"test:{text[:30]}",
    }
    payload.update(overrides)
    return payload


def vault_bytes(root: Path) -> bytes:
    chunks: list[bytes] = []
    for path in sorted(vault_path(root).rglob("*")):
        if path.is_file():
            chunks.append(path.read_bytes())
    return b"\n".join(chunks)


def test_init_and_immediate_capture_are_searchable_same_turn(tmp_path: Path) -> None:
    init_vault(tmp_path)
    result = capture(tmp_path, event("Production deployments use blue-green."))
    assert result["distilled"] is True
    assert result["memory_ids"]
    assert status(tmp_path)["pending"] == 0
    found = search(tmp_path, "blue green")
    assert found["results"][0]["id"] == result["memory_ids"][0]
    assert "blue-green" in (vault_path(tmp_path) / "MEMORY.md").read_text(encoding="utf-8")


def test_deferred_capture_is_recoverable_and_distilled_once(tmp_path: Path) -> None:
    payload = event("Release reviews happen on Thursday.", id="evt_release_review")
    result = capture(tmp_path, payload, defer=True)
    assert result["distilled"] is False
    assert status(tmp_path)["pending"] == 1
    first = distill(tmp_path)
    note_files = list((vault_path(tmp_path) / "notes").glob("*.md"))
    before = {path: path.read_bytes() for path in note_files}
    second = distill(tmp_path)
    assert first["processed"] == 1
    assert second["processed"] == 0
    assert before == {path: path.read_bytes() for path in note_files}


def test_event_replay_is_idempotent_and_conflicts_fail(tmp_path: Path) -> None:
    payload = event("Use pnpm for frontend dependencies.", id="evt_pkg_manager")
    first = capture(tmp_path, payload)
    second = capture(tmp_path, payload)
    assert first["memory_ids"] == second["memory_ids"]
    assert second["duplicate"] is True
    assert status(tmp_path)["events"] == 1
    with pytest.raises(MemorizerError, match="different content"):
        capture(tmp_path, {**payload, "text": "Use npm instead."})
    assert status(tmp_path)["events"] == 1


def test_equivalent_events_merge_provenance(tmp_path: Path) -> None:
    first = capture(tmp_path, event("Tests run with pytest.", id="evt_test_a", memory_key="testing:runner"))
    second = capture(tmp_path, event("Tests run with pytest.", id="evt_test_b", memory_key="testing:pytest"))
    assert first["memory_ids"] == second["memory_ids"]
    notes = load_notes(vault_path(tmp_path))
    assert list(notes.values())[0].source_event_ids == ["evt_test_a", "evt_test_b"]


def test_equivalent_events_merge_all_safe_metadata(tmp_path: Path) -> None:
    text = "The assistant should use compact release summaries."
    first = capture(
        tmp_path,
        event(
            text,
            id="evt_merge_meta_a",
            tags=["release"],
            entities=[{"name": "OpenAI", "type": "organization"}],
        ),
    )["memory_ids"][0]
    second = capture(
        tmp_path,
        event(
            text,
            id="evt_merge_meta_b",
            tags=["summary"],
            entities=[
                {"name": "openai", "type": "organization"},
                {"name": "Launch", "type": "project"},
            ],
            privacy="sensitive",
        ),
    )["memory_ids"][0]
    assert first == second
    note = load_notes(vault_path(tmp_path))[first]
    assert note.privacy == "sensitive"
    assert note.tags == ["release", "summary"]
    assert {entity["type"] for entity in note.entities} == {"organization", "project"}
    assert len([entity for entity in note.entities if entity["type"] == "organization"]) == 1
    assert note.source_event_ids == ["evt_merge_meta_a", "evt_merge_meta_b"]


def test_correction_supersedes_and_default_search_excludes_old(tmp_path: Path) -> None:
    original = capture(
        tmp_path,
        event("Production deployments use blue-green.", id="evt_deploy_old", memory_key="deploy:strategy"),
    )
    old_id = original["memory_ids"][0]
    corrected = capture(
        tmp_path,
        event(
            "Production deployments use canary releases.",
            id="evt_deploy_new",
            kind="correction",
            memory_key="deploy:strategy",
            supersedes=[old_id],
        ),
    )
    new_id = corrected["memory_ids"][0]
    notes = load_notes(vault_path(tmp_path))
    assert notes[old_id].status == "superseded"
    assert notes[old_id].superseded_by == new_id
    assert notes[new_id].supersedes == [old_id]
    assert [item["id"] for item in search(tmp_path, "production deployments")["results"]] == [new_id]
    assert {item["id"] for item in search(tmp_path, "production deployments", include_superseded=True)["results"]} == {
        old_id,
        new_id,
    }


def test_correction_chain_keeps_only_latest_active(tmp_path: Path) -> None:
    first = capture(tmp_path, event("Deployments use blue-green.", id="evt_chain_a"))["memory_ids"][0]
    second = capture(
        tmp_path,
        event("Deployments use canary.", id="evt_chain_b", kind="correction", supersedes=[first]),
    )["memory_ids"][0]
    third = capture(
        tmp_path,
        event("Deployments use progressive delivery.", id="evt_chain_c", kind="correction", supersedes=[second]),
    )["memory_ids"][0]
    notes = load_notes(vault_path(tmp_path))
    assert notes[first].superseded_by == second
    assert notes[second].superseded_by == third
    assert notes[third].status == "active"
    assert [item["id"] for item in search(tmp_path, "deployments use")["results"]] == [third]


def test_invalid_correction_does_not_supersede_anything(tmp_path: Path) -> None:
    init_vault(tmp_path)
    with pytest.raises(MemorizerError):
        capture(tmp_path, event("A correction without a target.", kind="correction"))
    assert status(tmp_path)["events"] == 0


def test_missing_correction_target_is_rejected_before_heartbeat(tmp_path: Path) -> None:
    init_vault(tmp_path)
    with pytest.raises(MemorizerError, match="missing memory"):
        capture(
            tmp_path,
            event(
                "Use canary releases.",
                id="evt_bad_target",
                kind="correction",
                supersedes=["mem_missing_target"],
            ),
        )
    assert status(tmp_path)["events"] == 0


def test_concurrent_deferred_corrections_allow_only_one_pending_target(tmp_path: Path) -> None:
    target = capture(tmp_path, event("Deployments use blue-green.", id="evt_concurrent_target"))["memory_ids"][0]

    def attempt(identifier: str, text: str) -> str:
        try:
            capture(
                tmp_path,
                event(text, id=identifier, kind="correction", supersedes=[target]),
                defer=True,
            )
            return "captured"
        except MemorizerError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda args: attempt(*args),
                [
                    ("evt_concurrent_correction_a", "Deployments use canary."),
                    ("evt_concurrent_correction_b", "Deployments use progressive delivery."),
                ],
            )
        )
    assert sorted(outcomes) == ["captured", "rejected"]
    assert status(tmp_path)["pending_events"] == 1
    result = distill(tmp_path)
    assert result["pending"] == 0
    assert status(tmp_path)["active"] == 1


@pytest.mark.parametrize(
    "secret",
    [
        "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz123456",
        "password=hunter2-super-secret",
        "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
        "postgresql://admin:very-secret-password@localhost/app",
    ],
)
def test_secrets_are_redacted_before_any_persistence(tmp_path: Path, secret: str) -> None:
    payload = event(
        f"The deployment credential is {secret}",
        id="evt_secret_" + str(abs(hash(secret))),
        title=f"Credential {secret}",
        kind="secret",
        tags=[secret],
        entities=[{"name": secret, "type": "system"}],
    )
    result = capture(tmp_path, payload)
    assert result["redacted"] is True
    persisted = vault_bytes(tmp_path)
    assert secret.encode() not in persisted
    assert base64_forbidden(secret) not in persisted
    shown = show(tmp_path, result["memory_ids"][0], touch=False)
    assert shown["privacy"] == "sensitive"
    validation = validate_vault(tmp_path)
    assert validation["valid"] is True, validation


@pytest.mark.parametrize(
    "text,secret",
    [
        ('Config is {"password":"hunter2-super-secret"}.', "hunter2-super-secret"),
        ('Config says password: "quoted-super-secret".', "quoted-super-secret"),
    ],
)
def test_quoted_secret_assignments_are_redacted(tmp_path: Path, text: str, secret: str) -> None:
    result = capture(tmp_path, event(text, id="evt_quoted_" + str(abs(hash(text))), kind="secret"))
    assert result["redacted"] is True
    assert secret.encode() not in vault_bytes(tmp_path)
    assert validate_vault(tmp_path)["valid"] is True


def test_redaction_is_idempotent_for_serialized_redacted_values() -> None:
    text = 'title: "Config says password: \\"[REDACTED]\\"."'
    assert memorizer_core.redact_text(text) == (text, False)


def test_sensitive_nested_metadata_key_is_redacted(tmp_path: Path) -> None:
    secret = "metadata-secret-value"
    result = capture(
        tmp_path,
        event(
            "A connector credential exists; its value must not be retained.",
            id="evt_nested_secret",
            kind="secret",
            source={"connector": "example", "password": secret},
        ),
    )
    assert result["redacted"] is True
    assert secret.encode() not in vault_bytes(tmp_path)


@pytest.mark.parametrize("key", ["secret", "token", "private_key"])
def test_serialized_sensitive_keys_are_redacted_before_persistence(tmp_path: Path, key: str) -> None:
    secret = f"rawvalue-{key}-DO-NOT-PERSIST-123456789"
    text = json.dumps({key: secret}, separators=(",", ":"))
    result = capture(tmp_path, event(text, id=f"evt_serialized_{key}", kind="secret"))
    assert result["redacted"] is True
    persisted = vault_bytes(tmp_path)
    assert secret.encode() not in persisted
    assert base64.urlsafe_b64encode(secret.encode()).rstrip(b"=") not in persisted
    assert validate_vault(tmp_path)["valid"] is True


def base64_forbidden(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64encode(value.encode()).rstrip(b"=")


def test_benign_password_policy_is_preserved(tmp_path: Path) -> None:
    text = "The password policy requires at least 14 characters."
    result = capture(tmp_path, event(text, id="evt_policy"))
    assert result["redacted"] is False
    assert text in show(tmp_path, result["memory_ids"][0], touch=False)["body"]


def test_unicode_and_frontmatter_injection_round_trip(tmp_path: Path) -> None:
    text = "Tên dự án: Sao Mai\n---\n[[not-a-real-link]]"
    result = capture(
        tmp_path,
        event(text, id="evt_unicode", title='Sao Mai: "alpha"', memory_key="project:sao-mai"),
    )
    shown = show(tmp_path, result["memory_ids"][0], touch=False)
    assert shown["title"] == 'Sao Mai: "alpha"'
    assert "Tên dự án" in shown["body"]
    validation = validate_vault(tmp_path)
    assert any("unresolved wikilink" in error for error in validation["errors"])


def test_workspaces_are_isolated(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    payload = event("Left workspace uses port 4111.", id="evt_shared")
    capture(left, payload)
    capture(right, {**payload, "text": "Right workspace uses port 5222.", "title": "Right port"})
    assert search(left, "4111")["results"]
    assert not search(left, "5222")["results"]
    assert search(right, "5222")["results"]


def test_concurrent_replay_creates_one_event_and_memory(tmp_path: Path) -> None:
    payload = event("Concurrent workers share a retry-safe event.", id="evt_concurrent")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: capture(tmp_path, payload), range(2)))
    assert sum(bool(result["duplicate"]) for result in results) == 1
    assert status(tmp_path)["events"] == 1
    assert status(tmp_path)["memories"] == 1


def test_pin_touch_and_rebuild_preserve_authoritative_metadata(tmp_path: Path) -> None:
    result = capture(tmp_path, event("Deploy checklist location is docs/deploy.md.", id="evt_checklist"))
    memory_id = result["memory_ids"][0]
    pin(tmp_path, memory_id)
    touch(tmp_path, memory_id)
    (vault_path(tmp_path) / "index.sqlite3").unlink()
    rebuild_index(tmp_path)
    shown = show(tmp_path, memory_id, touch=False)
    assert shown["pinned"] is True
    assert shown["revisit_count"] == 1
    assert validate_vault(tmp_path)["valid"] is True


def test_links_backlinks_and_graph_are_unique(tmp_path: Path) -> None:
    left = capture(tmp_path, event("API service owns request routing.", id="evt_api"))["memory_ids"][0]
    right = capture(tmp_path, event("Gateway delegates requests.", id="evt_gateway"))["memory_ids"][0]
    link(tmp_path, left, right, "depends-on")
    link(tmp_path, left, right, "depends-on")
    incoming = backlinks(tmp_path, right)["backlinks"]
    assert incoming == [{"source_id": left, "title": "API service owns request routing.", "relation_type": "depends-on"}]
    payload = graph(tmp_path, "json")
    assert len([edge for edge in payload["edges"] if edge["source"] == left and edge["target"] == right]) == 1
    mermaid = graph(tmp_path, "mermaid")
    assert "flowchart LR" in mermaid
    with pytest.raises(MemorizerError, match="self-links"):
        link(tmp_path, left, left, "self")


def test_link_rejects_empty_relation_without_partial_update(tmp_path: Path) -> None:
    source = capture(tmp_path, event("Source for strict link.", id="evt_strict_link_source"))["memory_ids"][0]
    target = capture(tmp_path, event("Target for strict link.", id="evt_strict_link_target"))["memory_ids"][0]
    before = show(tmp_path, source, touch=False)["relations"]
    with pytest.raises(MemorizerError, match="non-empty string"):
        link(tmp_path, source, target, "   ")
    assert show(tmp_path, source, touch=False)["relations"] == before


def test_case_equivalent_entities_share_one_complete_hub(tmp_path: Path) -> None:
    first = capture(
        tmp_path,
        event("OpenAI owns the first workflow.", id="evt_entity_case_a", entities=[{"name": "OpenAI", "type": "organization"}]),
    )["memory_ids"][0]
    second = capture(
        tmp_path,
        event("The second workflow also belongs to openai.", id="evt_entity_case_b", entities=[{"name": "openai", "type": "organization"}]),
    )["memory_ids"][0]
    hubs = list((vault_path(tmp_path) / "entities" / "organization").glob("*.md"))
    assert len(hubs) == 1
    hub = hubs[0].read_text(encoding="utf-8")
    assert first in hub and second in hub


def test_entity_seed_matching_uses_exact_tokens(tmp_path: Path) -> None:
    capture(
        tmp_path,
        event(
            "String operations are documented here.",
            id="evt_entity_token_boundary",
            entities=[{"name": "Concatenate", "type": "concept"}],
        ),
    )
    assert search(tmp_path, "cat")["results"] == []


def test_capture_relation_requires_stable_existing_target(tmp_path: Path) -> None:
    target = capture(tmp_path, event("The gateway is a core service.", id="evt_rel_target"))["memory_ids"][0]
    source = capture(
        tmp_path,
        event(
            "The API depends on the gateway.",
            id="evt_rel_source",
            relations=[{"type": "depends-on", "target": target, "target_kind": "note"}],
        ),
    )["memory_ids"][0]
    assert backlinks(tmp_path, target)["backlinks"][0]["source_id"] == source
    before = status(tmp_path)["events"]
    with pytest.raises(MemorizerError, match="missing memory"):
        capture(
            tmp_path,
            event(
                "This relation is broken.",
                id="evt_rel_broken",
                relations=[{"type": "depends-on", "target": "mem_missing", "target_kind": "note"}],
            ),
        )
    assert status(tmp_path)["events"] == before


def test_ranking_uses_pin_revisit_recency_and_entity_proximity(tmp_path: Path) -> None:
    timestamp = "2026-07-19T00:00:00Z"
    alpha = capture(
        tmp_path,
        event("Deployment guide for alpha.", id="evt_rank_alpha", captured_at=timestamp),
    )["memory_ids"][0]
    beta = capture(
        tmp_path,
        event("Deployment guide for beta.", id="evt_rank_beta", captured_at=timestamp, pinned=True),
    )["memory_ids"][0]
    assert search(tmp_path, "deployment guide")["results"][0]["id"] == beta
    pin(tmp_path, beta, pinned=False)
    touch(tmp_path, alpha)
    assert search(tmp_path, "deployment guide")["results"][0]["id"] == alpha

    old = capture(
        tmp_path,
        event("Release calendar for legacy.", id="evt_rank_old", captured_at="2025-01-01T00:00:00Z"),
    )["memory_ids"][0]
    recent = capture(
        tmp_path,
        event("Release calendar for current.", id="evt_rank_recent", captured_at="2026-07-19T00:00:00Z"),
    )["memory_ids"][0]
    assert search(tmp_path, "release calendar")["results"][0]["id"] == recent
    assert old != recent

    entity_note = capture(
        tmp_path,
        event(
            "Atlas service handles routes.",
            id="evt_rank_entity",
            entities=[{"name": "Atlas", "type": "system"}],
        ),
    )["memory_ids"][0]
    capture(tmp_path, event("Atlas service stores records.", id="evt_rank_plain"))
    entity_results = search(tmp_path, "Atlas service")["results"]
    assert entity_results[0]["id"] == entity_note
    assert entity_results[0]["related_entities"][0]["name"] == "Atlas"


def test_search_uses_bm25_and_actual_graph_neighbors(tmp_path: Path) -> None:
    target = capture(tmp_path, event("Atlas deployment controller.", id="evt_graph_target"))["memory_ids"][0]
    neighbor = capture(tmp_path, event("Runbook gamma contains fallback steps.", id="evt_graph_neighbor"))["memory_ids"][0]
    link(tmp_path, neighbor, target, "documents")
    results = search(tmp_path, "Atlas deployment")["results"]
    by_id = {item["id"]: item for item in results}
    assert target in by_id and neighbor in by_id
    assert by_id[target]["factors"]["bm25"] > 0
    assert by_id[neighbor]["factors"]["lexical"] == 0
    assert by_id[neighbor]["factors"]["graph"] == 1


def test_fts_metacharacters_do_not_break_search(tmp_path: Path) -> None:
    capture(tmp_path, event("The C++ build uses foo*bar and NEAR checks.", id="evt_fts"))
    for query in ('"foo" * NEAR(', "C++", "foo*bar"):
        result = search(tmp_path, query)
        assert "results" in result


def test_embedding_failure_falls_back_to_lexical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture(tmp_path, event("Runbooks live under operations/runbooks.", id="evt_runbooks"))
    monkeypatch.setenv("MEMORIZER_EMBEDDING_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("MEMORIZER_EMBEDDING_MODEL", "missing-model")
    result = search(tmp_path, "runbooks")
    assert result["results"]
    assert result["semantic_warning"]


def test_embedding_failure_preserves_lexical_token_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture(tmp_path, event("We concatenate strings here.", id="evt_token_boundary"))
    assert search(tmp_path, "cat")["results"] == []
    monkeypatch.setenv("MEMORIZER_EMBEDDING_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("MEMORIZER_EMBEDDING_MODEL", "missing-model")
    failed_semantic = search(tmp_path, "cat")
    assert failed_semantic["results"] == []
    assert failed_semantic["semantic_warning"]


def test_embedding_redirect_is_not_followed_or_given_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_by_target: list[str | None] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received_by_target.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            received_by_target.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header(
                "Location", f"http://127.0.0.1:{target.server_address[1]}/redirect-target"
            )
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in (target, redirect)
    ]
    for thread in threads:
        thread.start()
    monkeypatch.setenv("MEMORIZER_EMBEDDING_API_KEY", "redirect-secret-key")
    config = {
        "embedding": {
            "url": f"http://127.0.0.1:{redirect.server_address[1]}",
            "model": "redirect-test",
            "timeout_seconds": 2,
        }
    }
    try:
        vectors, warning = memorizer_core._embed(["private memory"], config)
    finally:
        for server in (redirect, target):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
    assert vectors == []
    assert warning
    assert received_by_target == []


def test_embedding_response_requires_exact_unique_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    client_class = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 0, "embedding": [0.0, 1.0]},
                ]
            },
        )
    )
    monkeypatch.setattr(
        memorizer_core.httpx,
        "Client",
        lambda **kwargs: client_class(transport=transport, **kwargs),
    )
    vectors, warning = memorizer_core._embed(
        ["first", "second"],
        {
            "embedding": {
                "url": "http://127.0.0.1:1234",
                "model": "bad-index-test",
                "timeout_seconds": 2,
            }
        },
    )
    assert vectors == []
    assert warning == "semantic search unavailable: ValueError"


def test_semantic_only_retrieval_uses_and_caches_local_embeddings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = capture(tmp_path, event("Apples are kept in the red cabinet.", id="evt_apples"))["memory_ids"][0]
    second = capture(tmp_path, event("Production rollout uses a progressive lane.", id="evt_rollout"))["memory_ids"][0]
    monkeypatch.setenv("MEMORIZER_EMBEDDING_URL", "http://127.0.0.1:1234")
    monkeypatch.setenv("MEMORIZER_EMBEDDING_MODEL", "test-embedding")

    def fake_embed(texts: list[str], config: dict[str, object]) -> tuple[list[list[float]], None]:
        vectors: list[list[float]] = []
        for text in texts:
            folded = text.casefold()
            vectors.append([1.0, 0.0] if "release approach" in folded or "rollout" in folded else [0.0, 1.0])
        return vectors, None

    monkeypatch.setattr(memorizer_core, "_embed", fake_embed)
    result = search(tmp_path, "release approach")
    assert result["results"][0]["id"] == second
    assert [item["id"] for item in result["results"]] == [second]
    with memorizer_core._connect(vault_path(tmp_path) / "index.sqlite3") as connection:
        cached = connection.execute("SELECT COUNT(*) FROM notes WHERE embedding_json IS NOT NULL").fetchone()[0]
    assert cached == 2


def test_slow_embedding_does_not_block_concurrent_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture(tmp_path, event("Existing semantic note.", id="evt_slow_existing"))
    monkeypatch.setenv("MEMORIZER_EMBEDDING_URL", "http://127.0.0.1:1234")
    monkeypatch.setenv("MEMORIZER_EMBEDDING_MODEL", "slow-test")
    entered = threading.Event()
    release = threading.Event()

    def slow_embed(texts: list[str], config: dict[str, object]) -> tuple[list[list[float]], None]:
        entered.set()
        assert release.wait(5)
        return [[1.0, 0.0] for _ in texts], None

    monkeypatch.setattr(memorizer_core, "_embed", slow_embed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        search_future = executor.submit(search, tmp_path, "semantic")
        assert entered.wait(2)
        started = time.monotonic()
        try:
            capture(tmp_path, event("Capture proceeds during embedding.", id="evt_during_embedding"))
        finally:
            release.set()
        assert time.monotonic() - started < 2
        assert search_future.result(timeout=5)["results"]


def test_distill_recovers_after_index_failure_without_duplicate_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_vault(tmp_path)
    real_rebuild = memorizer_core.rebuild_index_unlocked
    calls = 0

    def fail_once(vault: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated index failure")
        return real_rebuild(vault)

    monkeypatch.setattr(memorizer_core, "rebuild_index_unlocked", fail_once)
    with pytest.raises(OSError, match="simulated"):
        capture(tmp_path, event("The recovery fact remains durable.", id="evt_recovery"))
    assert status(tmp_path)["events"] == 1
    assert status(tmp_path)["memories"] == 1
    assert status(tmp_path)["derived_stale"] is True
    assert status(tmp_path)["pending"] == 1
    recovered = distill(tmp_path)
    assert recovered["processed"] == 0
    assert recovered["pending"] == 0
    assert search(tmp_path, "recovery fact")["results"]


def test_search_self_heals_deferred_and_stale_canonical_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deferred = capture(
        tmp_path,
        event("Phoenix uses gold deployments.", id="evt_search_recovery"),
        defer=True,
    )
    assert deferred["distilled"] is False
    assert search(tmp_path, "phoenix gold")["results"]
    assert status(tmp_path)["pending"] == 0

    real_rebuild = memorizer_core.rebuild_index_unlocked
    calls = 0

    def fail_once(vault: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated derived write failure")
        return real_rebuild(vault)

    monkeypatch.setattr(memorizer_core, "rebuild_index_unlocked", fail_once)
    with pytest.raises(OSError, match="simulated derived write failure"):
        capture(tmp_path, event("Orion uses silver deployments.", id="evt_stale_search"))
    assert status(tmp_path)["derived_stale"] is True
    assert search(tmp_path, "orion silver")["results"]
    assert status(tmp_path)["pending"] == 0


def test_distill_reconciles_partial_correction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old_id = capture(tmp_path, event("Deployments use blue-green.", id="evt_before"))["memory_ids"][0]
    real_write = memorizer_core.write_note
    failed = False

    def fail_old_supersession(vault: Path, note: memorizer_core.Note) -> None:
        nonlocal failed
        if note.id == old_id and note.status == "superseded" and not failed:
            failed = True
            raise OSError("simulated note failure")
        real_write(vault, note)

    monkeypatch.setattr(memorizer_core, "write_note", fail_old_supersession)
    with pytest.raises(OSError, match="simulated"):
        capture(
            tmp_path,
            event(
                "Deployments use canary releases.",
                id="evt_after",
                kind="correction",
                supersedes=[old_id],
                memory_key="deploy:strategy",
            ),
        )
    partial = status(tmp_path)
    assert partial["pending_events"] == 1
    assert partial["derived_stale"] is True
    assert validate_vault(tmp_path)["valid"] is False
    recovery = distill(tmp_path)
    notes = load_notes(vault_path(tmp_path))
    assert recovery["repaired"] == 1
    assert notes[old_id].status == "superseded"
    assert sum(note.status == "active" for note in notes.values()) == 1


def test_validation_detects_and_rebuild_repairs_index_drift(tmp_path: Path) -> None:
    result = capture(tmp_path, event("The service port is 8443.", id="evt_port"))
    note_path = Path(show(tmp_path, result["memory_ids"][0], touch=False)["path"])
    text = note_path.read_text(encoding="utf-8")
    note_path.write_text(text.replace("8443", "9443"), encoding="utf-8")
    assert validate_vault(tmp_path)["valid"] is False
    rebuild_index(tmp_path)
    assert validate_vault(tmp_path)["valid"] is True
    assert search(tmp_path, "9443")["results"]


def test_rebuild_discovers_manual_note_and_preserves_old_index_on_failure(tmp_path: Path) -> None:
    init_vault(tmp_path)
    vault = vault_path(tmp_path)
    manual = Note(
        id="mem_manual001",
        title="Manual operating convention",
        kind="project-knowledge",
        body="Manual reviews happen on Friday.",
        created_at="2026-07-19T00:00:00Z",
        updated_at="2026-07-19T00:00:00Z",
        memory_key="manual:review-day",
    )
    write_note(vault, manual)
    rebuild_index(tmp_path)
    assert search(tmp_path, "reviews Friday")["results"][0]["id"] == manual.id

    bad_path = vault / "notes" / "broken.md"
    bad_path.write_text("not valid frontmatter\n", encoding="utf-8")
    with pytest.raises(MemorizerError, match="missing JSON-valued YAML"):
        rebuild_index(tmp_path)
    bad_path.unlink()
    assert search(tmp_path, "reviews Friday")["results"][0]["id"] == manual.id


def test_rebuild_on_fresh_workspace_initializes_complete_layout(tmp_path: Path) -> None:
    result = rebuild_index(tmp_path)
    vault = vault_path(tmp_path)
    assert result["notes"] == 0
    assert (vault / "config.json").is_file()
    assert (vault / "MEMORY.md").is_file()
    assert (vault / "index.sqlite3").is_file()
    assert all((vault / name).is_dir() for name in ("daily", "notes", "entities"))
    assert validate_vault(tmp_path)["valid"] is True


def test_rebuild_refuses_manual_secret_without_propagating_it(tmp_path: Path) -> None:
    result = capture(tmp_path, event("The service uses a managed credential.", id="evt_manual_secret"))
    note_path = Path(show(tmp_path, result["memory_ids"][0], touch=False)["path"])
    secret = "manual-secret-value"
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace(
            "The service uses a managed credential.", f"password={secret}"
        ),
        encoding="utf-8",
    )
    with pytest.raises(MemorizerError, match="redact the source note"):
        rebuild_index(tmp_path)
    for path in vault_path(tmp_path).rglob("*"):
        if path.is_file() and path != note_path:
            assert secret.encode() not in path.read_bytes(), path
    validation = validate_vault(tmp_path)
    assert validation["valid"] is False
    assert any("unredacted credential" in error for error in validation["errors"])


def test_path_rename_drift_is_detected_and_rebuilt(tmp_path: Path) -> None:
    result = capture(tmp_path, event("Path drift remains detectable.", id="evt_path_drift"))
    old_path = Path(show(tmp_path, result["memory_ids"][0], touch=False)["path"])
    new_path = old_path.with_name("renamed-memory.md")
    old_path.rename(new_path)
    validation = validate_vault(tmp_path)
    assert validation["valid"] is False
    assert any("drifted" in error for error in validation["errors"])
    rebuild_index(tmp_path)
    assert validate_vault(tmp_path)["valid"] is True


def test_corrupt_index_is_rebuilt_for_graph_and_search(tmp_path: Path) -> None:
    captured = capture(tmp_path, event("Corrupt indexes are recoverable.", id="evt_corrupt_index"))["memory_ids"][0]
    (vault_path(tmp_path) / "index.sqlite3").write_bytes(b"not-a-sqlite-database")
    payload = graph(tmp_path, "json")
    assert captured in {node["id"] for node in payload["nodes"]}
    assert search(tmp_path, "recoverable")["results"][0]["id"] == captured


def test_all_derived_tables_are_checked_and_reader_repaired(tmp_path: Path) -> None:
    target = capture(tmp_path, event("Atlas owns routing.", id="evt_integrity_target"))["memory_ids"][0]
    source = capture(
        tmp_path,
        event(
            "Gateway depends on Atlas.",
            id="evt_integrity_source",
            entities=[{"name": "Atlas", "type": "system"}],
        ),
    )["memory_ids"][0]
    link(tmp_path, source, target, "depends-on")
    index_path = vault_path(tmp_path) / "index.sqlite3"

    connection = sqlite3.connect(index_path)
    try:
        connection.execute("DELETE FROM notes_fts")
        connection.commit()
    finally:
        connection.close()
    assert status(tmp_path)["derived_stale"] is True
    assert validate_vault(tmp_path)["valid"] is False
    assert search(tmp_path, "Atlas routing")["results"]

    connection = sqlite3.connect(index_path)
    try:
        row = connection.execute(
            "SELECT id,title,body,tags,entities FROM notes_fts ORDER BY id LIMIT 1"
        ).fetchone()
        assert row is not None
        connection.execute("INSERT INTO notes_fts(id,title,body,tags,entities) VALUES(?,?,?,?,?)", row)
        connection.commit()
    finally:
        connection.close()
    assert status(tmp_path)["derived_stale"] is True
    assert validate_vault(tmp_path)["valid"] is False
    assert search(tmp_path, "Atlas routing")["results"]

    connection = sqlite3.connect(index_path)
    try:
        connection.execute("DELETE FROM links")
        connection.commit()
    finally:
        connection.close()
    assert status(tmp_path)["derived_stale"] is True
    assert backlinks(tmp_path, target)["backlinks"]

    connection = sqlite3.connect(index_path)
    try:
        connection.execute("DELETE FROM entities")
        connection.commit()
    finally:
        connection.close()
    assert status(tmp_path)["derived_stale"] is True
    graph_payload = graph(tmp_path, "json")
    assert any(node["label"] == "Atlas" for node in graph_payload["nodes"])
    assert validate_vault(tmp_path)["valid"] is True


def test_generated_memory_and_entity_views_are_checked_and_repaired(tmp_path: Path) -> None:
    capture(
        tmp_path,
        event(
            "Atlas is the routing system.",
            id="evt_view_integrity",
            entities=[{"name": "Atlas", "type": "system"}],
        ),
    )
    vault = vault_path(tmp_path)
    memory_path = vault / "MEMORY.md"
    entity_path = next((vault / "entities" / "system").glob("*.md"))
    memory_path.unlink()
    entity_path.unlink()
    state = status(tmp_path)
    assert state["derived_stale"] is True
    assert validate_vault(tmp_path)["valid"] is False
    assert search(tmp_path, "Atlas routing")["results"]
    assert memory_path.exists()
    assert list((vault / "entities" / "system").glob("*.md"))
    assert validate_vault(tmp_path)["valid"] is True


def test_backlinks_self_heal_after_link_index_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = capture(tmp_path, event("Source memory.", id="evt_link_failure_source"))["memory_ids"][0]
    target = capture(tmp_path, event("Target memory.", id="evt_link_failure_target"))["memory_ids"][0]
    real_rebuild = memorizer_core.rebuild_index_unlocked
    calls = 0

    def fail_once(vault: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated link index failure")
        return real_rebuild(vault)

    monkeypatch.setattr(memorizer_core, "rebuild_index_unlocked", fail_once)
    with pytest.raises(OSError, match="simulated link index failure"):
        link(tmp_path, source, target, "depends-on")
    assert status(tmp_path)["derived_stale"] is True
    assert backlinks(tmp_path, target)["backlinks"][0]["source_id"] == source


def test_invalid_embedding_config_is_reported_without_type_traceback(tmp_path: Path) -> None:
    init_vault(tmp_path)
    config_path = vault_path(tmp_path) / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["embedding"]["url"] = 123
    config_path.write_text(json.dumps(config), encoding="utf-8")
    validation = validate_vault(tmp_path)
    assert validation["valid"] is False
    assert any("embedding url and model" in error for error in validation["errors"])
    with pytest.raises(MemorizerError, match="embedding url and model"):
        search(tmp_path, "anything")


@pytest.mark.parametrize("target", ["config", "note"])
def test_invalid_utf8_is_reported_by_validation(tmp_path: Path, target: str) -> None:
    init_vault(tmp_path)
    vault = vault_path(tmp_path)
    if target == "config":
        (vault / "config.json").write_bytes(b"\xff\xfe")
    else:
        (vault / "notes" / "invalid-utf8.md").write_bytes(b"\xff\xfe")
    validation = validate_vault(tmp_path)
    assert validation["valid"] is False
    assert any("decode" in error.casefold() or "codec" in error.casefold() for error in validation["errors"])


def test_escaped_surrogates_are_rejected_at_capture_and_note_boundaries(tmp_path: Path) -> None:
    init_vault(tmp_path)
    payload = event("Unicode scalar validation.", id="evt_surrogate", title=chr(0xD800))
    with pytest.raises(MemorizerError, match="Unicode"):
        capture(tmp_path, payload)
    assert status(tmp_path)["events"] == 0

    note = Note(
        id="mem_surrogate_note",
        title="Manual surrogate note",
        kind="project-knowledge",
        body="Safe body.",
        created_at="2026-07-19T00:00:00Z",
        updated_at="2026-07-19T00:00:00Z",
        memory_key="manual:surrogate",
    )
    write_note(vault_path(tmp_path), note)
    assert note.path is not None
    raw = note.path.read_text(encoding="utf-8")
    note.path.write_text(
        raw.replace('title: "Manual surrogate note"', 'title: "\\ud800"'),
        encoding="utf-8",
    )
    validation = validate_vault(tmp_path)
    assert validation["valid"] is False
    assert any("Unicode" in error for error in validation["errors"])


def test_manual_unknown_frontmatter_survives_supported_updates(tmp_path: Path) -> None:
    result = capture(tmp_path, event("The owner is the platform team.", id="evt_owner"))
    memory_id = result["memory_ids"][0]
    note_path = Path(show(tmp_path, memory_id, touch=False)["path"])
    text = note_path.read_text(encoding="utf-8")
    note_path.write_text(text.replace("---\n\n#", 'custom_field: {"safe": true}\n---\n\n#', 1), encoding="utf-8")
    rebuild_index(tmp_path)
    pin(tmp_path, memory_id)
    assert 'custom_field: {"safe": true}' in note_path.read_text(encoding="utf-8")


def test_invalid_payload_has_no_partial_event(tmp_path: Path) -> None:
    init_vault(tmp_path)
    before = status(tmp_path)
    with pytest.raises(MemorizerError):
        capture(tmp_path, {"kind": "unknown", "text": "bad"})
    assert status(tmp_path) == before


@pytest.mark.parametrize(
    "payload,error",
    [
        (
            event("A normal event cannot supersede.", supersedes=["mem_target"]),
            "only valid for correction",
        ),
        (
            event("Entity names must be meaningful.", entities=[{"name": "   ", "type": "concept"}]),
            "non-empty name",
        ),
        (event("Pinned must be typed.", pinned="false"), "pinned must be a boolean"),
    ],
)
def test_payload_schema_rejects_ambiguous_values_without_partial_event(
    tmp_path: Path, payload: dict[str, object], error: str
) -> None:
    init_vault(tmp_path)
    before = status(tmp_path)
    with pytest.raises(MemorizerError, match=error):
        capture(tmp_path, payload)
    assert status(tmp_path) == before


@pytest.mark.parametrize(
    "mutate,error",
    [
        (lambda payload: payload.pop("kind"), "requires a signal kind"),
        (lambda payload: payload.pop("title"), "requires a non-empty title"),
        (lambda payload: payload.pop("memory_key"), "requires a non-empty string memory_key"),
        (lambda payload: payload.update(memory_key={"bad": True}), "string memory_key"),
        (lambda payload: payload.update(id=""), "event id must use"),
        (lambda payload: payload.update(captured_at=""), "invalid ISO-8601 timestamp"),
        (lambda payload: payload.update(captured_at=123), "invalid ISO-8601 timestamp"),
        (lambda payload: payload.update(kind={"bad": True}), "requires a signal kind"),
        (lambda payload: payload.update(privacy={"bad": True}), "privacy must be"),
        (
            lambda payload: payload.update(entities=[{"name": "Atlas", "type": {"bad": True}}]),
            "unknown entity type",
        ),
        (
            lambda payload: payload.update(
                relations=[{"type": "links", "target": "mem_target", "target_kind": {"bad": True}}]
            ),
            "target_kind must be note or entity",
        ),
    ],
)
def test_capture_required_fields_and_malformed_types_are_stable(
    tmp_path: Path, mutate: object, error: str
) -> None:
    init_vault(tmp_path)
    payload = event("Strict capture schema.", id="evt_strict_schema")
    mutate(payload)  # type: ignore[operator]
    with pytest.raises(MemorizerError, match=error):
        capture(tmp_path, payload)
    assert status(tmp_path)["events"] == 0


def test_orphan_lock_file_is_recovered_immediately(tmp_path: Path) -> None:
    init_vault(tmp_path)
    lock_path = vault_path(tmp_path) / ".write.lock"
    lock_path.write_text("999999 2000-01-01T00:00:00Z\n", encoding="utf-8")
    started = time.monotonic()
    assert status(tmp_path)["pending"] == 0
    assert time.monotonic() - started < 1.0


def test_process_termination_releases_vault_lock(tmp_path: Path) -> None:
    init_vault(tmp_path)
    helper = (
        "import pathlib,sys,time;"
        "from local_knowledge.memorizer.core import vault_lock;"
        "vault=pathlib.Path(sys.argv[1]);"
        "manager=vault_lock(vault);manager.__enter__();"
        "print('locked',flush=True);time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", helper, str(vault_path(tmp_path))],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
    finally:
        process.terminate()
        process.wait(timeout=5)
    started = time.monotonic()
    assert status(tmp_path)["pending"] == 0
    assert time.monotonic() - started < 1.0


def test_truncated_daily_event_is_reported_not_silently_lost(tmp_path: Path) -> None:
    result = capture(tmp_path, event("A deferred durable event.", id="evt_truncated"), defer=True)
    daily_path = Path(result["daily_path"])
    raw = daily_path.read_bytes()
    daily_path.write_bytes(raw[:-8])
    with pytest.raises(MemorizerError, match="truncated or malformed event framing"):
        status(tmp_path)
    validation = validate_vault(tmp_path)
    assert validation["valid"] is False
    assert any("truncated or malformed event framing" in error for error in validation["errors"])


def test_literal_event_marker_text_does_not_break_daily_framing(tmp_path: Path) -> None:
    text = "Documentation includes the literal <!-- memorizer:event marker."
    result = capture(tmp_path, event(text, id="evt_literal_marker"))
    assert result["distilled"] is True
    assert status(tmp_path)["pending"] == 0
    assert search(tmp_path, "literal marker")["results"]


def test_literal_event_heading_text_does_not_break_daily_framing(tmp_path: Path) -> None:
    text = "## 12:34:56Z · decision · evt_fake"
    result = capture(tmp_path, event(text, id="evt_literal_heading"))
    assert result["distilled"] is True
    assert status(tmp_path)["pending"] == 0
    assert search(tmp_path, "evt fake")["results"]


def test_malformed_event_object_is_reported_as_schema_error(tmp_path: Path) -> None:
    result = capture(tmp_path, event("Deferred journal object.", id="evt_bad_object"), defer=True)
    daily_path = Path(result["daily_path"])
    text = daily_path.read_text(encoding="utf-8")
    daily_path.write_text(
        re.sub(
            r"<!-- memorizer:event [A-Za-z0-9_-]+ -->",
            "<!-- memorizer:event e30 -->",
            text,
            count=1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(MemorizerError, match="invalid event schema"):
        status(tmp_path)
    validation = validate_vault(tmp_path)
    assert validation["valid"] is False
    assert any("invalid event schema" in error for error in validation["errors"])


def test_daily_heading_must_match_encoded_event_metadata(tmp_path: Path) -> None:
    result = capture(tmp_path, event("Deferred heading check.", id="evt_heading_check"), defer=True)
    daily_path = Path(result["daily_path"])
    text = daily_path.read_text(encoding="utf-8")
    daily_path.write_text(text.replace("evt_heading_check", "evt_heading_wrong", 1), encoding="utf-8")
    with pytest.raises(MemorizerError, match="heading and metadata disagree"):
        status(tmp_path)
    assert validate_vault(tmp_path)["valid"] is False


def test_visible_daily_heartbeat_must_match_encoded_event(tmp_path: Path) -> None:
    result = capture(tmp_path, event("Original visible fact.", id="evt_visible_tamper"), defer=True)
    daily_path = Path(result["daily_path"])
    text = daily_path.read_text(encoding="utf-8")
    daily_path.write_text(
        text.replace("Original visible fact.", "Tampered visible fact.", 1),
        encoding="utf-8",
    )
    with pytest.raises(MemorizerError, match="visible heartbeat and encoded event disagree"):
        status(tmp_path)
    assert validate_vault(tmp_path)["valid"] is False


def test_validation_waits_for_writer_lock(tmp_path: Path) -> None:
    capture(tmp_path, event("Validation uses a consistent snapshot.", id="evt_validation_lock"))
    with ThreadPoolExecutor(max_workers=1) as executor:
        with vault_lock(vault_path(tmp_path)):
            future = executor.submit(validate_vault, tmp_path)
            time.sleep(0.15)
            assert not future.done()
        assert future.result(timeout=2)["valid"] is True
