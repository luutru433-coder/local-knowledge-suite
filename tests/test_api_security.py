# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from local_knowledge.ckb.api import create_app
from local_knowledge.ckb.config import Settings, packaged_portal_dir
from local_knowledge.ckb.db import Database
from local_knowledge.ckb.security import create_user


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def insert_concept(connection, concept_id: str, branch_id: int, concept_status: str) -> None:
    connection.execute(
        "INSERT INTO concepts("
        "id,branch_id,type,title,description,body,tags_json,status,quality_json,path"
        ") VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            concept_id,
            branch_id,
            "Reference",
            concept_id.replace("-", " ").title(),
            "Concept used by API authorization tests.",
            "Test concept body.",
            "[]",
            concept_status,
            "{}",
            f"reference/{concept_id}.md",
        ),
    )


def test_login_csrf_and_role_enforcement(settings) -> None:
    db = Database(settings.database)
    db.initialize()
    create_user(db, "admin", "administrator-password", "admin")
    create_user(db, "reader", "reader-password-123", "reader")
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as admin:
        csrf = login(admin, "admin", "administrator-password")
        rejected = admin.post("/api/v1/users", json={"username": "reviewer", "password": "reviewer-password", "role": "reviewer"})
        assert rejected.status_code == 403
        created = admin.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": csrf},
            json={"username": "reviewer", "password": "reviewer-password", "role": "reviewer"},
        )
        assert created.status_code == 201
        assert admin.get("/api/v1/users").status_code == 200
        synced = admin.post("/api/v1/git/pull", headers={"X-CSRF-Token": csrf})
        # This unit-test Settings root is not an owned company Git repository.
        # Authorization succeeds, then the repository preflight fails closed.
        assert synced.status_code == 409
    with TestClient(app, base_url="http://127.0.0.1") as reader:
        login(reader, "reader", "reader-password-123")
        assert reader.get("/api/v1/sources").status_code == 200
        assert reader.get("/api/v1/users").status_code == 403


def test_health_reports_missing_ocr_without_failing(settings) -> None:
    response = TestClient(
        create_app(settings),
        base_url="http://127.0.0.1",
    ).get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] is True
    assert "tesseract_available" in payload["ocr"]
    assert "vi_available" in payload["ocr"]


@pytest.mark.parametrize(
    "host",
    [
        "attacker.example:8000",
        "localhost.attacker.example:8000",
        "0.0.0.0:8000",
        "192.168.1.10:8000",
        "*:8000",
        "[2001:db8::1]:8000",
    ],
)
def test_non_loopback_host_headers_are_rejected(settings, host: str) -> None:
    response = TestClient(
        create_app(settings),
        base_url="http://127.0.0.1",
    ).get("/api/v1/health", headers={"Host": host})
    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_security_headers_harden_normal_and_rejected_host_responses(settings) -> None:
    client = TestClient(create_app(settings), base_url="http://127.0.0.1")
    responses = [
        client.get("/api/v1/health"),
        client.get("/api/v1/health", headers={"Host": "attacker.example"}),
    ]
    assert [response.status_code for response in responses] == [200, 400]
    for response in responses:
        assert response.headers["content-security-policy"] == "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "localhost:8000",
        "127.0.0.1:8000",
        "127.99.12.4:8000",
        "[::1]:8000",
    ],
)
def test_loopback_host_headers_are_allowed(settings, host: str) -> None:
    response = TestClient(
        create_app(settings),
        base_url="http://127.0.0.1",
    ).get("/api/v1/health", headers={"Host": host})
    assert response.status_code == 200


def test_default_api_does_not_grant_cross_origin_credentials(settings) -> None:
    client = TestClient(create_app(settings), base_url="http://127.0.0.1")
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers
    assert client.get("/api/v1/health").status_code == 200


def test_explicit_loopback_developer_origin_is_narrowly_allowed(settings) -> None:
    settings.cors_origins = ("http://127.0.0.1:5173",)
    response = TestClient(
        create_app(settings),
        base_url="http://127.0.0.1",
    ).options(
        "/api/v1/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_built_portal_is_served(settings) -> None:
    assert packaged_portal_dir() is not None
    response = TestClient(
        create_app(settings),
        base_url="http://127.0.0.1",
    ).get("/")
    assert response.status_code == 200
    assert "Local Knowledge Suite Portal" in response.text


def test_company_portal_cannot_override_packaged_portal(settings) -> None:
    company_portal = settings.root / "web" / "dist"
    company_portal.mkdir(parents=True)
    marker = "COMPANY_CONTROLLED_SCRIPT_MUST_NOT_RUN"
    (company_portal / "index.html").write_text(
        f"<script>{marker}</script>",
        encoding="utf-8",
    )

    loaded = Settings.load(settings.root)
    trusted_portal = packaged_portal_dir()
    assert trusted_portal is not None
    assert loaded.portal_dir == trusted_portal
    assert loaded.portal_dir != company_portal

    # Even an in-process mutation cannot redirect the API to company content.
    loaded.portal_dir = company_portal
    response = TestClient(
        create_app(loaded),
        base_url="http://127.0.0.1",
    ).get("/")
    assert response.status_code == 200
    assert "Local Knowledge Suite Portal" in response.text
    assert marker not in response.text


def test_reader_portal_starts_from_non_main_canonical_branch(settings) -> None:
    settings.canonical_branch = "production"
    app = create_app(settings)
    create_user(app.state.service.db, "production-reader", "reader-password-123", "reader")

    with TestClient(app, base_url="http://127.0.0.1") as reader:
        login(reader, "production-reader", "reader-password-123")
        assert reader.get("/").status_code == 200
        branches = reader.get("/api/v1/branches")
        assert branches.status_code == 200
        assert [(item["name"], bool(item["is_canonical"])) for item in branches.json()] == [("production", True)]
        assert reader.get("/api/v1/concepts?branch=main").status_code == 403
        production_concepts = reader.get("/api/v1/concepts?branch=production")
        assert production_concepts.status_code == 200
        assert production_concepts.json() == []


def test_reader_sees_only_published_concepts_and_verified_claims(settings) -> None:
    app = create_app(settings)
    db = app.state.service.db
    create_user(db, "admin", "administrator-password", "admin")
    create_user(db, "reviewer", "reviewer-password-123", "reviewer")
    create_user(db, "reader", "reader-password-123", "reader")
    with db.transaction(immediate=True) as connection:
        branch_id = int(connection.execute("SELECT id FROM branches WHERE name='main'").fetchone()["id"])
        insert_concept(connection, "published-policy", branch_id, "published")
        insert_concept(connection, "draft-policy", branch_id, "review")
        connection.execute(
            "INSERT INTO claims(concept_id,text,confidence,citations_json,verified) VALUES(?,?,?,?,1)",
            ("published-policy", "Verified reader-safe claim.", 0.99, '[{"source_uri":"file:///verified.txt"}]'),
        )
        connection.execute(
            "INSERT INTO claims(concept_id,text,confidence,citations_json,verified) VALUES(?,?,?,?,0)",
            ("published-policy", "Unverified internal review claim.", 0.40, "[]"),
        )

    with TestClient(app, base_url="http://127.0.0.1") as reader:
        reader_csrf = login(reader, "reader", "reader-password-123")
        listed = reader.get("/api/v1/concepts?status_filter=review")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == ["published-policy"]
        detail = reader.get("/api/v1/concepts/published-policy")
        assert detail.status_code == 200
        assert [claim["text"] for claim in detail.json()["claims"]] == ["Verified reader-safe claim."]
        assert reader.get("/api/v1/concepts/draft-policy").status_code == 404
        assert reader.post(
            "/api/v1/feedback",
            headers={"X-CSRF-Token": reader_csrf},
            json={"query": "draft", "details": "must stay hidden", "concept_id": "draft-policy"},
        ).status_code == 404
        accepted_feedback = reader.post(
            "/api/v1/feedback",
            headers={"X-CSRF-Token": reader_csrf},
            json={"query": "published", "details": "visible concept", "concept_id": "published-policy"},
        )
        assert accepted_feedback.status_code == 201

    credentials = [
        ("admin", "administrator-password"),
        ("reviewer", "reviewer-password-123"),
        ("reader", "reader-password-123"),
    ]
    for username, password in credentials:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            csrf = login(client, username, password)
            headers = {"X-CSRF-Token": csrf}
            assert client.post("/api/v1/concepts/draft-policy/endorse", headers=headers).status_code == 404
            assert client.delete("/api/v1/concepts/draft-policy/endorse", headers=headers).status_code == 404
            assert client.post("/api/v1/concepts/draft-policy/usage", headers=headers).status_code == 404
    with db.connect() as connection:
        draft = connection.execute(
            "SELECT endorsements,usage_count FROM concepts WHERE id='draft-policy'"
        ).fetchone()
        assert (draft["endorsements"], draft["usage_count"]) == (0, 0)


def test_feedback_moderation_is_isolated_by_branch_membership(settings) -> None:
    app = create_app(settings)
    db = app.state.service.db
    admin_id = create_user(db, "admin", "administrator-password", "admin")
    reviewer_id = create_user(db, "reviewer", "reviewer-password-123", "reviewer")
    with db.transaction(immediate=True) as connection:
        branch_ids: dict[str, int] = {}
        for name in ("alpha", "beta", "gamma"):
            cursor = connection.execute(
                "INSERT INTO branches(name,is_canonical,protected) VALUES(?,0,1)",
                (name,),
            )
            branch_ids[name] = int(cursor.lastrowid)
            insert_concept(connection, f"{name}-concept", branch_ids[name], "review")
        connection.executemany(
            "INSERT INTO branch_members(branch_id,user_id,role) VALUES(?,?,?)",
            [
                (branch_ids["alpha"], reviewer_id, "reviewer"),
                (branch_ids["beta"], reviewer_id, "reader"),
                (branch_ids["gamma"], reviewer_id, "admin"),
            ],
        )
        feedback_ids: dict[str, int] = {}
        for name in ("alpha", "beta", "gamma"):
            cursor = connection.execute(
                "INSERT INTO feedback(user_id,query,details,concept_id) VALUES(?,?,?,?)",
                (admin_id, name, f"{name} feedback", f"{name}-concept"),
            )
            feedback_ids[name] = int(cursor.lastrowid)
        cursor = connection.execute(
            "INSERT INTO feedback(user_id,query,details,concept_id) VALUES(?,?,?,NULL)",
            (admin_id, "global", "global feedback"),
        )
        feedback_ids["global"] = int(cursor.lastrowid)

    with TestClient(app, base_url="http://127.0.0.1") as reviewer:
        csrf = login(reviewer, "reviewer", "reviewer-password-123")
        visible = reviewer.get("/api/v1/feedback")
        assert visible.status_code == 200
        assert {item["id"] for item in visible.json()} == {
            feedback_ids["alpha"],
            feedback_ids["gamma"],
        }
        for name in ("alpha", "gamma"):
            response = reviewer.patch(
                f"/api/v1/feedback/{feedback_ids[name]}",
                headers={"X-CSRF-Token": csrf},
                json={"status": "resolved"},
            )
            assert response.status_code == 200
        for name in ("beta", "global"):
            response = reviewer.patch(
                f"/api/v1/feedback/{feedback_ids[name]}",
                headers={"X-CSRF-Token": csrf},
                json={"status": "resolved"},
            )
            assert response.status_code == 404

    with TestClient(app, base_url="http://127.0.0.1") as admin:
        csrf = login(admin, "admin", "administrator-password")
        visible = admin.get("/api/v1/feedback")
        assert visible.status_code == 200
        assert {item["id"] for item in visible.json()} == set(feedback_ids.values())
        response = admin.patch(
            f"/api/v1/feedback/{feedback_ids['global']}",
            headers={"X-CSRF-Token": csrf},
            json={"status": "resolved"},
        )
        assert response.status_code == 200
