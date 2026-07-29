# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from ipaddress import ip_address
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__ as RUNTIME_VERSION
from .config import Settings, packaged_portal_dir
from .db import Database
from .gitops import GitOperationError, pull, push, status as git_status
from .models import (
    BranchCreate,
    BranchMemberUpdate,
    ClaimRevision,
    FeedbackCreate,
    FeedbackUpdate,
    GitCredentialSet,
    LoginRequest,
    ReviewDecision,
    SearchRequest,
    SecretSet,
    SourceCreate,
    UserCreate,
)
from .okf import validate_bundle
from .parsers import ocr_health
from .pipeline import KnowledgeService
from .search import search
from .security import authenticate, create_session, create_user, delete_session, get_session_user
from .secrets_store import SecretStore, SecretStoreError


def _is_allowed_loopback_host(value: str) -> bool:
    candidate = value.strip()
    if (
        not candidate
        or candidate != value
        or any(character.isspace() for character in candidate)
        or any(character in candidate for character in ("/", "\\", "@", "\x00"))
    ):
        return False

    host = candidate
    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing <= 1:
            return False
        host = candidate[1:closing]
        remainder = candidate[closing + 1 :]
        if remainder:
            if not remainder.startswith(":") or not _valid_host_port(remainder[1:]):
                return False
    else:
        try:
            return ip_address(candidate).is_loopback
        except ValueError:
            pass
        if candidate.count(":") == 1:
            host, port = candidate.rsplit(":", 1)
            if not _valid_host_port(port):
                return False
        elif ":" in candidate:
            # HTTP Host requires brackets around an IPv6 address.
            return False

    if host.casefold() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _valid_host_port(value: str) -> bool:
    return value.isascii() and value.isdigit() and 1 <= int(value) <= 65535


class LoopbackHostMiddleware:
    """Reject DNS-rebinding Host headers before an API route can run."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if scope.get("type") == "http":
            hosts = [
                raw_value.decode("latin-1")
                for raw_name, raw_value in scope.get("headers", [])
                if raw_name.lower() == b"host"
            ]
            if len(hosts) != 1 or not _is_allowed_loopback_host(hosts[0]):
                response = Response(
                    content="Invalid host header",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    media_type="text/plain",
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


SECURITY_RESPONSE_HEADERS = (
    (b"content-security-policy", b"frame-ancestors 'none'; base-uri 'self'; object-src 'none'"),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)
SECURITY_RESPONSE_HEADER_NAMES = frozenset(name for name, _ in SECURITY_RESPONSE_HEADERS)


class SecurityHeadersMiddleware:
    """Apply browser hardening headers to every HTTP response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in SECURITY_RESPONSE_HEADER_NAMES
                ]
                message = {**message, "headers": [*headers, *SECURITY_RESPONSE_HEADERS]}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.load()
    service = KnowledgeService(app_settings)
    db = service.db
    secret_store = SecretStore(db, app_settings.keyring_service)
    app = FastAPI(title="Local Knowledge Suite", version=RUNTIME_VERSION)
    app.state.settings = app_settings
    app.state.service = service
    app.state.secret_store = secret_store
    try:
        service.lm.bearer_token = secret_store.get("lm_studio_token")
    except SecretStoreError:
        service.lm.bearer_token = None
    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(app_settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )
    app.add_middleware(LoopbackHostMiddleware)
    # Added last so it wraps the Host gate and also hardens rejected Host responses.
    app.add_middleware(SecurityHeadersMiddleware)

    def current_user(ckb_session: str | None = Cookie(default=None)) -> dict[str, Any]:
        user = get_session_user(db, ckb_session)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        return user

    def csrf_user(
        request: Request,
        user: dict[str, Any] = Depends(current_user),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            cookie = request.cookies.get("ckb_csrf")
            if not cookie or not x_csrf_token or cookie != x_csrf_token or x_csrf_token != user["csrf_token"]:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid CSRF token")
        return user

    def require(*roles: str, csrf: bool = False) -> Callable[..., dict[str, Any]]:
        dependency = csrf_user if csrf else current_user

        def check(user: dict[str, Any] = Depends(dependency)) -> dict[str, Any]:
            if user["role"] not in roles:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
            return user

        return check

    def resolve_branch(name: str | None, user: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
        branch_name = name or app_settings.canonical_branch
        with db.connect() as connection:
            row = connection.execute("SELECT * FROM branches WHERE name=?", (branch_name,)).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "branch access denied")
        role = service.branch_role(user, int(row["id"]))
        if role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "branch access denied")
        return dict(row)

    def require_concept_access(
        concept_id: str,
        user: dict[str, Any],
        allowed: set[str],
        *,
        published_for_readers: bool = False,
        published_only: bool = False,
    ) -> tuple[dict[str, Any], str]:
        with db.connect() as connection:
            row = connection.execute("SELECT * FROM concepts WHERE id=?", (concept_id,)).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "concept not found")
        branch_role = service.branch_role(user, int(row["branch_id"]))
        if branch_role not in allowed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "concept not found")
        if (published_only or (published_for_readers and branch_role == "reader")) and row["status"] != "published":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "concept not found")
        return dict(row), str(branch_role)

    def require_published_status(connection: Any, concept_id: str) -> None:
        row = connection.execute("SELECT status FROM concepts WHERE id=?", (concept_id,)).fetchone()
        if row is None or row["status"] != "published":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "concept not found")

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        with db.connect() as connection:
            database_ok = connection.execute("SELECT 1").fetchone()[0] == 1
        lm_health = service.lm.health()
        secret_health = secret_store.health()
        bundle_validation = validate_bundle(app_settings.bundle_dir)
        secrets_ready = bool(secret_health.get("available")) or not secret_health.get("configured")
        ready = database_ok and bool(lm_health.get("reachable")) and bool(lm_health.get("chat_endpoint")) and secrets_ready and not bundle_validation
        return {
            "status": "ok" if ready else "degraded",
            "database": database_ok,
            "lm_studio": lm_health,
            "ocr": ocr_health(),
            "secrets": secret_health,
            "bundle": {"path": str(app_settings.bundle_dir), "validation": bundle_validation},
        }

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        user = authenticate(db, payload.username, payload.password)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        token, csrf, expires = create_session(db, int(user["id"]), app_settings.session_hours)
        response.set_cookie("ckb_session", token, httponly=True, secure=app_settings.secure_cookies, samesite="strict", max_age=app_settings.session_hours * 3600)
        response.set_cookie("ckb_csrf", csrf, httponly=False, secure=app_settings.secure_cookies, samesite="strict", max_age=app_settings.session_hours * 3600)
        return {"user": user, "csrf_token": csrf, "expires_at": expires}

    @app.post("/api/v1/auth/logout")
    def logout(
        response: Response,
        user: dict[str, Any] = Depends(csrf_user),
        ckb_session: str | None = Cookie(default=None),
    ) -> dict[str, bool]:
        delete_session(db, ckb_session)
        response.delete_cookie("ckb_session")
        response.delete_cookie("ckb_csrf")
        return {"ok": True}

    @app.get("/api/v1/auth/me")
    def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return {"id": user["id"], "username": user["username"], "role": user["role"]}

    @app.get("/api/v1/users")
    def list_users(_: dict[str, Any] = Depends(require("admin"))) -> list[dict[str, Any]]:
        with db.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT id,username,role,active,created_at FROM users ORDER BY username")]

    @app.post("/api/v1/users", status_code=201)
    def add_user(payload: UserCreate, _: dict[str, Any] = Depends(require("admin", csrf=True))) -> dict[str, Any]:
        try:
            user_id = create_user(db, payload.username, payload.password, payload.role)
        except Exception as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return {"id": user_id, "username": payload.username, "role": payload.role}

    @app.get("/api/v1/branches")
    def list_branches(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        with db.connect() as connection:
            if user["role"] == "admin":
                rows = connection.execute("SELECT * FROM branches ORDER BY is_canonical DESC,name").fetchall()
            else:
                rows = connection.execute(
                    "SELECT b.*,bm.role AS member_role FROM branches b JOIN branch_members bm ON bm.branch_id=b.id "
                    "WHERE bm.user_id=? ORDER BY b.is_canonical DESC,b.name",
                    (user["id"],),
                ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/v1/branches", status_code=201)
    def add_branch(payload: BranchCreate, user: dict[str, Any] = Depends(require("admin", csrf=True))) -> dict[str, Any]:
        try:
            return service.create_branch(payload.name, int(user["id"]))
        except Exception as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    @app.get("/api/v1/branches/{branch_id}/members")
    def branch_members(branch_id: int, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        role = service.branch_role(user, branch_id)
        if role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "branch access denied")
        with db.connect() as connection:
            rows = connection.execute(
                "SELECT u.id,u.username,bm.role FROM branch_members bm JOIN users u ON u.id=bm.user_id WHERE bm.branch_id=? ORDER BY u.username",
                (branch_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/v1/branches/{branch_id}/members")
    def update_branch_member(branch_id: int, payload: BranchMemberUpdate, user: dict[str, Any] = Depends(csrf_user)) -> dict[str, Any]:
        if service.branch_role(user, branch_id) != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "branch access denied")
        try:
            service.set_branch_member(branch_id, payload.user_id, payload.role, int(user["id"]))
        except Exception as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return {"branch_id": branch_id, "user_id": payload.user_id, "role": payload.role}

    @app.get("/api/v1/sources")
    def list_sources(user: dict[str, Any] = Depends(require("admin", "reviewer", "reader"))) -> list[dict[str, Any]]:
        with db.connect() as connection:
            if user["role"] == "admin":
                rows = connection.execute("SELECT s.*,b.name AS branch FROM sources s JOIN branches b ON b.id=s.branch_id ORDER BY s.created_at DESC").fetchall()
            else:
                rows = connection.execute(
                    "SELECT s.*,b.name AS branch FROM sources s JOIN branches b ON b.id=s.branch_id "
                    "JOIN branch_members bm ON bm.branch_id=s.branch_id WHERE bm.user_id=? ORDER BY s.created_at DESC",
                    (user["id"],),
                ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["allowed_domains"] = json.loads(row["allowed_domains"])
        return result

    @app.post("/api/v1/sources", status_code=201)
    def add_source(payload: SourceCreate, user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        try:
            branch = resolve_branch(payload.branch, user, {"admin", "reviewer"})
            source_id = service.add_source(payload.kind, payload.uri, payload.title, payload.allowed_domains, int(user["id"]), branch["name"])
        except Exception as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return {"id": source_id}

    @app.post("/api/v1/sources/{source_id}/ingest", status_code=202)
    def ingest(source_id: int, user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        with db.connect() as connection:
            source = connection.execute("SELECT branch_id FROM sources WHERE id=?", (source_id,)).fetchone()
        if source is None or service.branch_role(user, int(source["branch_id"])) not in {"admin", "reviewer"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
        try:
            job_id = service.enqueue(source_id, int(user["id"]))
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return {"job_id": job_id, "status": "queued"}

    @app.get("/api/v1/jobs")
    def jobs(user: dict[str, Any] = Depends(require("admin", "reviewer", "reader"))) -> list[dict[str, Any]]:
        with db.connect() as connection:
            if user["role"] == "admin":
                rows = connection.execute("SELECT j.*,s.branch_id,b.name AS branch FROM jobs j JOIN sources s ON s.id=j.source_id JOIN branches b ON b.id=s.branch_id ORDER BY j.created_at DESC LIMIT 200").fetchall()
            else:
                rows = connection.execute(
                    "SELECT j.*,s.branch_id,b.name AS branch FROM jobs j JOIN sources s ON s.id=j.source_id JOIN branches b ON b.id=s.branch_id "
                    "JOIN branch_members bm ON bm.branch_id=s.branch_id WHERE bm.user_id=? ORDER BY j.created_at DESC LIMIT 200",
                    (user["id"],),
                ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            if item.get("cancel_requested_at") and item["status"] == "running":
                item["status"] = "cancelling"
            if service.branch_role(user, int(item["branch_id"])) == "reader":
                for key in ("worker_id", "lease_token", "lease_until", "heartbeat_at"):
                    item.pop(key, None)
        return result

    @app.post("/api/v1/jobs/{job_id}/run")
    def run_job(job_id: int, user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        with db.connect() as connection:
            job = connection.execute("SELECT s.branch_id FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.id=?", (job_id,)).fetchone()
        if job is None or service.branch_role(user, int(job["branch_id"])) not in {"admin", "reviewer"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
        try:
            return service.run_job(job_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: int, user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        with db.connect() as connection:
            job = connection.execute("SELECT j.status,s.branch_id FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.id=?", (job_id,)).fetchone()
        if job is None or service.branch_role(user, int(job["branch_id"])) not in {"admin", "reviewer"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
        if not service.cancel_job(job_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "job is not queued or running")
        return {"id": job_id, "status": "cancelled" if job["status"] == "queued" else "cancelling"}

    @app.post("/api/v1/jobs/{job_id}/retry")
    def retry_job(job_id: int, user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        with db.connect() as connection:
            job = connection.execute("SELECT s.branch_id FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.id=?", (job_id,)).fetchone()
        if job is None or service.branch_role(user, int(job["branch_id"])) not in {"admin", "reviewer"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
        if not service.retry_job(job_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "job is not failed or cancelled")
        return {"id": job_id, "status": "queued"}

    @app.post("/api/v1/search")
    def query(payload: SearchRequest, user: dict[str, Any] = Depends(require("admin", "reviewer", "reader"))) -> dict[str, Any]:
        branch = resolve_branch(payload.branch, user, {"admin", "reviewer", "reader"})
        return search(db, payload.query, payload.limit, service.lm, payload.concept_type, payload.tags, int(branch["id"]))

    @app.get("/api/v1/concepts")
    def concepts(
        status_filter: str | None = None,
        branch: str | None = None,
        user: dict[str, Any] = Depends(require("admin", "reviewer", "reader")),
    ) -> list[dict[str, Any]]:
        branch_row = resolve_branch(branch, user, {"admin", "reviewer", "reader"})
        branch_role = service.branch_role(user, int(branch_row["id"]))
        sql = "SELECT id,branch_id,type,title,description,tags_json,status,quality_json,path,maturity,pagerank,legacy,endorsements,usage_count,created_at,updated_at FROM concepts WHERE branch_id=?"
        params: tuple[Any, ...] = (branch_row["id"],)
        if branch_role == "reader":
            sql += " AND status='published'"
        elif status_filter:
            sql += " AND status=?"
            params = (branch_row["id"], status_filter)
        sql += " ORDER BY updated_at DESC"
        with db.connect() as connection:
            rows = [dict(row) for row in connection.execute(sql, params)]
        for row in rows:
            row["tags"] = json.loads(row.pop("tags_json"))
            row["quality"] = json.loads(row.pop("quality_json"))
        return rows

    @app.get("/api/v1/concepts/{concept_id}")
    def concept(concept_id: str, user: dict[str, Any] = Depends(require("admin", "reviewer", "reader"))) -> dict[str, Any]:
        concept_row, branch_role = require_concept_access(
            concept_id,
            user,
            {"admin", "reviewer", "reader"},
            published_for_readers=True,
        )
        with db.connect() as connection:
            claim_sql = "SELECT id,text,confidence,citations_json,verified FROM claims WHERE concept_id=?"
            if branch_role == "reader":
                claim_sql += " AND verified=1"
            claims = connection.execute(claim_sql, (concept_id,)).fetchall()
            entities = connection.execute(
                "SELECT e.name FROM entities e JOIN concept_entities ce ON ce.entity_id=e.id WHERE ce.concept_id=? ORDER BY e.name",
                (concept_id,),
            ).fetchall()
        result = concept_row
        result["tags"] = json.loads(result.pop("tags_json"))
        result["quality"] = json.loads(result.pop("quality_json"))
        result["claims"] = [{**dict(item), "citations": json.loads(item["citations_json"])} for item in claims]
        result["entities"] = [item["name"] for item in entities]
        for item in result["claims"]:
            item.pop("citations_json", None)
        return result

    @app.post("/api/v1/concepts/{concept_id}/review")
    def review(concept_id: str, payload: ReviewDecision, user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        require_concept_access(concept_id, user, {"admin", "reviewer"})
        try:
            return service.review(concept_id, payload.decision, payload.edited_title, payload.edited_body, actor=user)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except GitOperationError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    @app.patch("/api/v1/concepts/{concept_id}/claims/{claim_id}")
    def revise_claim(concept_id: str, claim_id: int, payload: ClaimRevision, user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        require_concept_access(concept_id, user, {"admin", "reviewer"})
        try:
            return service.revise_claim(concept_id, claim_id, payload.text, payload.locator, payload.excerpt, user)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    @app.post("/api/v1/concepts/{concept_id}/endorse")
    def endorse(concept_id: str, user: dict[str, Any] = Depends(require("admin", "reviewer", "reader", csrf=True))) -> dict[str, Any]:
        require_concept_access(concept_id, user, {"admin", "reviewer", "reader"}, published_only=True)
        with db.transaction(immediate=True) as connection:
            require_published_status(connection, concept_id)
            connection.execute("INSERT OR IGNORE INTO endorsements(user_id,concept_id) VALUES(?,?)", (user["id"], concept_id))
            count = connection.execute("SELECT COUNT(*) FROM endorsements WHERE concept_id=?", (concept_id,)).fetchone()[0]
            connection.execute("UPDATE concepts SET endorsements=? WHERE id=?", (count, concept_id))
        return {"id": concept_id, "endorsements": count}

    @app.delete("/api/v1/concepts/{concept_id}/endorse")
    def remove_endorsement(concept_id: str, user: dict[str, Any] = Depends(require("admin", "reviewer", "reader", csrf=True))) -> dict[str, Any]:
        require_concept_access(concept_id, user, {"admin", "reviewer", "reader"}, published_only=True)
        with db.transaction(immediate=True) as connection:
            require_published_status(connection, concept_id)
            connection.execute("DELETE FROM endorsements WHERE user_id=? AND concept_id=?", (user["id"], concept_id))
            count = connection.execute("SELECT COUNT(*) FROM endorsements WHERE concept_id=?", (concept_id,)).fetchone()[0]
            connection.execute("UPDATE concepts SET endorsements=? WHERE id=?", (count, concept_id))
        return {"id": concept_id, "endorsements": count}

    @app.post("/api/v1/concepts/{concept_id}/usage")
    def record_usage(concept_id: str, user: dict[str, Any] = Depends(require("admin", "reviewer", "reader", csrf=True))) -> dict[str, Any]:
        require_concept_access(concept_id, user, {"admin", "reviewer", "reader"}, published_only=True)
        today = datetime.now(UTC).date().isoformat()
        with db.transaction(immediate=True) as connection:
            require_published_status(connection, concept_id)
            connection.execute("INSERT OR IGNORE INTO usage_events(user_id,concept_id,usage_day) VALUES(?,?,?)", (user["id"], concept_id, today))
            count = connection.execute("SELECT COUNT(*) FROM usage_events WHERE concept_id=?", (concept_id,)).fetchone()[0]
            connection.execute("UPDATE concepts SET usage_count=? WHERE id=?", (count, concept_id))
        return {"id": concept_id, "usage_count": count}

    @app.get("/api/v1/feedback")
    def list_feedback(user: dict[str, Any] = Depends(require("admin", "reviewer"))) -> list[dict[str, Any]]:
        with db.connect() as connection:
            if user["role"] == "admin":
                rows = connection.execute("SELECT * FROM feedback ORDER BY created_at DESC").fetchall()
            else:
                rows = connection.execute(
                    "SELECT f.* FROM feedback f "
                    "JOIN concepts c ON c.id=f.concept_id "
                    "JOIN branch_members bm ON bm.branch_id=c.branch_id AND bm.user_id=? "
                    "WHERE bm.role IN ('admin','reviewer') "
                    "ORDER BY f.created_at DESC",
                    (user["id"],),
                ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/v1/feedback", status_code=201)
    def add_feedback(payload: FeedbackCreate, user: dict[str, Any] = Depends(require("admin", "reviewer", "reader", csrf=True))) -> dict[str, Any]:
        concept_branch_role: str | None = None
        if payload.concept_id is not None:
            _, concept_branch_role = require_concept_access(
                payload.concept_id,
                user,
                {"admin", "reviewer", "reader"},
                published_for_readers=True,
            )
        with db.transaction(immediate=True) as connection:
            if payload.concept_id is not None and concept_branch_role == "reader":
                require_published_status(connection, payload.concept_id)
            cursor = connection.execute(
                "INSERT INTO feedback(user_id,query,details,concept_id) VALUES(?,?,?,?)",
                (user["id"], payload.query, payload.details, payload.concept_id),
            )
            return {"id": cursor.lastrowid}

    @app.patch("/api/v1/feedback/{feedback_id}")
    def update_feedback(feedback_id: int, payload: FeedbackUpdate, user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        with db.transaction(immediate=True) as connection:
            feedback = connection.execute(
                "SELECT f.id,f.concept_id,c.branch_id FROM feedback f "
                "LEFT JOIN concepts c ON c.id=f.concept_id WHERE f.id=?",
                (feedback_id,),
            ).fetchone()
            if feedback is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "feedback not found")
            if user["role"] != "admin":
                branch_id = feedback["branch_id"]
                if branch_id is None or service.branch_role(user, int(branch_id)) not in {"admin", "reviewer"}:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "feedback not found")
            cursor = connection.execute(
                "UPDATE feedback SET status=?,resolved_by=?,resolved_at=? WHERE id=?",
                (
                    payload.status,
                    user["id"] if payload.status == "resolved" else None,
                    datetime.now(UTC).isoformat() if payload.status == "resolved" else None,
                    feedback_id,
                ),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status.HTTP_409_CONFLICT, "feedback update was not applied")
        return {"id": feedback_id, "status": payload.status}

    @app.get("/api/v1/publications")
    def publications(user: dict[str, Any] = Depends(require("admin", "reviewer"))) -> list[dict[str, Any]]:
        with db.connect() as connection:
            if user["role"] == "admin":
                rows = connection.execute(
                    "SELECT p.*,c.title,b.name AS branch FROM publications p JOIN concepts c ON c.id=p.concept_id JOIN branches b ON b.id=p.branch_id ORDER BY p.created_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT p.*,c.title,b.name AS branch FROM publications p JOIN concepts c ON c.id=p.concept_id "
                    "JOIN branches b ON b.id=p.branch_id JOIN branch_members bm ON bm.branch_id=p.branch_id "
                    "WHERE bm.user_id=? ORDER BY p.created_at DESC",
                    (user["id"],),
                ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/v1/publications/{publication_id}/merge")
    def merge_publication(publication_id: str, user: dict[str, Any] = Depends(csrf_user)) -> dict[str, Any]:
        with db.connect() as connection:
            publication = connection.execute("SELECT branch_id FROM publications WHERE id=?", (publication_id,)).fetchone()
        if publication is None or service.branch_role(user, int(publication["branch_id"])) != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "branch access denied")
        try:
            return service.merge_publication(publication_id, user)
        except (ValueError, GitOperationError) as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    @app.get("/api/v1/entities")
    def entities(branch: str | None = None, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        branch_row = resolve_branch(branch, user, {"admin", "reviewer", "reader"})
        with db.connect() as connection:
            rows = connection.execute(
                "SELECT e.id,e.name,e.slug,e.aliases_json,e.pagerank,COUNT(ce.concept_id) AS concept_count "
                "FROM entities e JOIN concept_entities ce ON ce.entity_id=e.id JOIN concepts c ON c.id=ce.concept_id "
                "WHERE c.branch_id=? AND c.status='published' GROUP BY e.id ORDER BY e.pagerank DESC,e.name",
                (branch_row["id"],),
            ).fetchall()
        return [{**dict(row), "aliases": json.loads(row["aliases_json"])} for row in rows]

    @app.get("/api/v1/entities/{entity_id}")
    def entity(entity_id: int, branch: str | None = None, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        branch_row = resolve_branch(branch, user, {"admin", "reviewer", "reader"})
        with db.connect() as connection:
            row = connection.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
            concepts = connection.execute(
                "SELECT c.id,c.title,c.type,c.description,c.path,c.pagerank FROM concepts c JOIN concept_entities ce ON ce.concept_id=c.id "
                "WHERE ce.entity_id=? AND c.branch_id=? AND c.status='published' ORDER BY c.pagerank DESC,c.title",
                (entity_id, branch_row["id"]),
            ).fetchall()
        if row is None or not concepts:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "entity not found")
        return {**dict(row), "aliases": json.loads(row["aliases_json"]), "concepts": [dict(item) for item in concepts]}

    @app.get("/api/v1/secrets/status")
    def secret_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        result: dict[str, Any] = {"git": secret_store.status(int(user["id"]))}
        if user["role"] == "admin":
            result["global"] = secret_store.status(None)
        return result

    @app.put("/api/v1/secrets/lm-studio")
    def set_lm_secret(payload: SecretSet, user: dict[str, Any] = Depends(require("admin", csrf=True))) -> dict[str, bool]:
        try:
            secret_store.set("lm_studio_token", payload.value)
            service.lm.bearer_token = payload.value
        except SecretStoreError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        service.audit(int(user["id"]), None, "secret.set", "secret", "lm_studio_token", "succeeded")
        return {"configured": True}

    @app.delete("/api/v1/secrets/lm-studio")
    def delete_lm_secret(user: dict[str, Any] = Depends(require("admin", csrf=True))) -> dict[str, bool]:
        deleted = secret_store.delete("lm_studio_token")
        service.lm.bearer_token = None
        service.audit(int(user["id"]), None, "secret.delete", "secret", "lm_studio_token", "succeeded")
        return {"deleted": deleted}

    @app.put("/api/v1/secrets/git")
    def set_git_secret(payload: GitCredentialSet, user: dict[str, Any] = Depends(csrf_user)) -> dict[str, bool]:
        try:
            secret_store.set_json("git_https_credentials", {"username": payload.username, "token": payload.token}, int(user["id"]))
        except SecretStoreError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        service.audit(int(user["id"]), None, "secret.set", "secret", "git_https_credentials", "succeeded")
        return {"configured": True}

    @app.delete("/api/v1/secrets/git")
    def delete_git_secret(user: dict[str, Any] = Depends(csrf_user)) -> dict[str, bool]:
        deleted = secret_store.delete("git_https_credentials", int(user["id"]))
        service.audit(int(user["id"]), None, "secret.delete", "secret", "git_https_credentials", "succeeded")
        return {"deleted": deleted}

    @app.get("/api/v1/git/status")
    def repository_status(_: dict[str, Any] = Depends(require("admin", "reviewer"))) -> dict[str, str]:
        return git_status(app_settings.root)

    @app.post("/api/v1/git/push")
    def repository_push(user: dict[str, Any] = Depends(require("admin", csrf=True))) -> dict[str, bool]:
        try:
            push(app_settings.root, secret_store.get_json("git_https_credentials", int(user["id"])))
        except (GitOperationError, SecretStoreError, ValueError, RuntimeError) as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        with db.transaction(immediate=True) as connection:
            connection.execute("UPDATE publications SET state='pushed',updated_at=? WHERE state='applied'", (datetime.now(UTC).isoformat(),))
        return {"ok": True}

    @app.post("/api/v1/git/pull")
    def repository_pull(user: dict[str, Any] = Depends(require("admin", "reviewer", csrf=True))) -> dict[str, Any]:
        try:
            result: dict[str, Any] = pull(
                app_settings.root,
                secret_store.get_json("git_https_credentials", int(user["id"])),
            )
            result["rebuilt_concepts"] = service.rebuild_from_bundle()
            return result
        except (GitOperationError, SecretStoreError, ValueError, RuntimeError) as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # Never serve HTML or JavaScript from a company-controlled repository.
    # The packaged portal is part of the trusted runtime and is reparse-checked.
    web_dist = packaged_portal_dir()
    if web_dist is not None and (web_dist / "index.html").is_file():
        assets = web_dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            requested = (web_dist / path).resolve()
            if path and requested.is_relative_to(web_dist) and requested.is_file():
                return FileResponse(requested)
            return FileResponse(web_dist / "index.html")

    return app
