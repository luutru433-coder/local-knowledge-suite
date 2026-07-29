# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from .ckb.config import Settings
from .ckb.db import Database
from .ckb.pipeline import KnowledgeService
from .ckb.search import search as ckb_search
from .memorizer import core as memory_core
from .winio import reject_reparse_traversal
from .workspace import WorkspaceContext


class SkillProvider(Protocol):
    def status(self, context: WorkspaceContext) -> dict[str, Any]: ...
    def search(self, context: WorkspaceContext, query: str, limit: int) -> dict[str, Any]: ...


class MemoryProvider(Protocol):
    def initialize(self, context: WorkspaceContext) -> dict[str, Any]: ...
    def status(self, context: WorkspaceContext) -> dict[str, Any]: ...
    def search(self, context: WorkspaceContext, query: str, limit: int, include_sensitive: bool) -> dict[str, Any]: ...
    def capture(self, context: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]: ...


class CompanyProvider(Protocol):
    def initialize(self, context: WorkspaceContext) -> dict[str, Any]: ...
    def status(self, context: WorkspaceContext) -> dict[str, Any]: ...
    def search(self, context: WorkspaceContext, query: str, limit: int) -> dict[str, Any]: ...


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold().replace("\u0111", "d"))
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9._/-]*", _fold(value)))


def _excerpt(text: str, query: str, size: int = 1200) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= size:
        return compact
    folded = _fold(compact)
    positions = [folded.find(token) for token in _tokens(query)]
    positions = [position for position in positions if position >= 0]
    start = max(0, (min(positions) if positions else 0) - size // 4)
    return compact[start : start + size].strip()


class BundledSkillProvider:
    def __init__(self, extra_roots: tuple[Path, ...] = ()) -> None:
        plugin_skills = Path(__file__).resolve().parents[3] / "skills"
        self.extra_roots = (plugin_skills, *extra_roots)

    def _paths(self, context: WorkspaceContext) -> list[Path]:
        roots = (context.project_root / "skills", *self.extra_roots)
        unique: dict[str, Path] = {}
        for root in roots:
            if root.is_dir():
                for path in root.rglob("SKILL.md"):
                    unique[str(path.resolve()).casefold()] = path.resolve()
        return sorted(unique.values(), key=lambda path: str(path).casefold())

    def status(self, context: WorkspaceContext) -> dict[str, Any]:
        paths = self._paths(context)
        return {"available": bool(paths), "count": len(paths)}

    def search(self, context: WorkspaceContext, query: str, limit: int) -> dict[str, Any]:
        query_tokens = _tokens(query)
        results: list[dict[str, Any]] = []
        for path in self._paths(context):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            name = path.parent.name
            description = ""
            if text.startswith("---"):
                _, frontmatter, _ = text.split("---", 2)
                for line in frontmatter.splitlines():
                    key, separator, value = line.partition(":")
                    if separator and key.strip() == "name":
                        name = value.strip().strip('"\'')
                    if separator and key.strip() == "description":
                        description = value.strip().strip('"\'')
            haystack = _tokens(f"{name} {description} {text}")
            overlap = len(query_tokens & haystack)
            phrase = 2 if _fold(query) in _fold(f"{name} {description}") else 0
            score = float(overlap + phrase)
            if score <= 0:
                continue
            results.append(
                {
                    "source": "skill",
                    "authority": "instruction",
                    "name": name,
                    "description": description,
                    "path": str(path),
                    "excerpt": _excerpt(text, query, 700),
                    "score": score,
                }
            )
        results.sort(key=lambda item: (-float(item["score"]), str(item["name"])))
        return {"available": bool(self._paths(context)), "results": results[:limit]}


class BundledMemoryProvider:
    def _root(self, context: WorkspaceContext) -> Path:
        if context.project.memory_path != ".memorizer":
            raise ValueError("this runtime supports the fixed project memory path .memorizer")
        return context.project_root

    def initialize(self, context: WorkspaceContext) -> dict[str, Any]:
        return dict(memory_core.init_vault(self._root(context)))

    def status(self, context: WorkspaceContext) -> dict[str, Any]:
        if not context.memory_root.is_dir():
            return {"available": False, "pending": 0, "warning": "memory vault is not initialized"}
        return {"available": True, **dict(memory_core.status(self._root(context)))}

    def search(self, context: WorkspaceContext, query: str, limit: int, include_sensitive: bool) -> dict[str, Any]:
        if not context.memory_root.is_dir():
            return {"available": False, "results": [], "warning": "memory vault is not initialized"}
        response = dict(memory_core.search(self._root(context), query, limit))
        results = []
        for item in response.get("results", []):
            if item.get("privacy") == "sensitive" and not include_sensitive:
                continue
            results.append({"source": "memory", "authority": "remembered_context", **item})
        response.update({"available": True, "results": results})
        return response

    def capture(self, context: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(memory_core.capture(self._root(context), payload, defer=False))
        state = dict(memory_core.status(self._root(context)))
        distillation = result.get("distillation") or {}
        conflicts = int(distillation.get("conflicts", 0))
        rejected = int(distillation.get("rejected", 0))
        accepted = bool(
            result.get("distilled")
            and result.get("memory_ids")
            and int(state.get("pending", 0)) == 0
            and conflicts == 0
            and rejected == 0
        )
        return {
            **result,
            "ok": accepted,
            "accepted": accepted,
            "conflicts": conflicts,
            "rejected": rejected,
            "pending": int(state.get("pending", 0)),
            "status": state,
        }


def company_settings(context: WorkspaceContext) -> Settings:
    if context.company_root is None or context.company is None:
        raise ValueError("company knowledge is disabled by this project's profile")
    return Settings.for_company(context.company_root, context.company.company_id)


def _citations(row: sqlite3.Row) -> tuple[list[dict[str, Any]], bool]:
    try:
        parsed = json.loads(row["citations_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        parsed = None
    structurally_valid = isinstance(parsed, list) and all(
        isinstance(item, dict) for item in parsed
    )
    citations = (
        [dict(item) for item in parsed]
        if structurally_valid
        else []
    )
    if (
        structurally_valid
        and not citations
        and row["source_uri"]
        and row["locator"]
        and row["excerpt"]
    ):
        citations = [{
            "source_uri": row["source_uri"],
            "locator": row["locator"],
            "excerpt": row["excerpt"],
            "checksum": row["document_checksum"],
        }]
    return citations, structurally_valid


def _current_company_source_matches(
    context: WorkspaceContext,
    source_uri: str,
    checksum: str,
) -> bool:
    if context.company_root is None or context.company is None:
        return False
    parsed = urlparse(source_uri)
    scheme = parsed.scheme.casefold()
    if scheme in {"http", "https"}:
        return True
    if scheme != "company-source" or parsed.netloc.casefold() != context.company.company_id.casefold():
        return False
    relative_text = unquote(parsed.path.lstrip("/"))
    relative = Path(*relative_text.split("/"))
    private_parts = {".ckb", ".git", ".local-knowledge", ".memorizer", "knowledge"}
    if (
        not relative_text
        or relative.is_absolute()
        or any(
            part in {"", ".", ".."}
            or ":" in part
            or "\\" in part
            or part.casefold() in private_parts
            for part in relative.parts
        )
    ):
        return False
    source_root = context.company_root / ".local-sources"
    candidate = source_root / relative
    try:
        reject_reparse_traversal(source_root, candidate, "company citation source")
        source_root_resolved = source_root.resolve(strict=True)
        candidate_resolved = candidate.resolve(strict=True)
        if os.path.commonpath(
            (os.path.normcase(str(source_root_resolved)), os.path.normcase(str(candidate_resolved)))
        ) != os.path.normcase(str(source_root_resolved)):
            return False
        return (
            candidate_resolved.is_file()
            and hashlib.sha256(candidate_resolved.read_bytes()).hexdigest() == checksum.casefold()
        )
    except (OSError, ValueError):
        return False


def _verified_citation(
    context: WorkspaceContext,
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    citation: dict[str, Any],
    *,
    primary: bool,
) -> dict[str, Any]:
    source_uri = citation.get("source_uri")
    locator = citation.get("locator")
    excerpt = citation.get("excerpt")
    checksum = citation.get("checksum")
    fields_valid = all(
        isinstance(value, str) and bool(value)
        for value in (source_uri, locator, excerpt, checksum)
    )
    excerpt_matches = False
    if fields_valid:
        excerpt_matches = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM chunks "
            "WHERE document_id=? AND locator=? AND instr(text,?)>0)",
            (row["document_id"], locator, excerpt),
        ).fetchone()[0]
    canonical_primary_matches = (
        not primary
        or (
            locator == row["locator"]
            and excerpt == row["excerpt"]
        )
    )
    verified = bool(
        fields_valid
        and row["verified"]
        and row["document_checksum"]
        and row["document_checksum"] == row["ingested_checksum"]
        and checksum == row["document_checksum"]
        and row["source_uri"] == row["ingested_source_uri"]
        and source_uri == row["source_uri"]
        and canonical_primary_matches
        and excerpt_matches
        and _current_company_source_matches(
            context,
            str(source_uri),
            str(checksum),
        )
    )
    return {**citation, "verified": verified}


class BundledCompanyProvider:
    def initialize(self, context: WorkspaceContext) -> dict[str, Any]:
        settings = company_settings(context)
        settings.ensure_directories()
        database = Database(settings.database)
        database.initialize()
        with database.connect() as connection:
            concept_count = int(connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0])
        rebuilt = 0
        if concept_count == 0 and any(
            path.name not in {"index.md", "log.md"}
            for path in settings.bundle_dir.rglob("*.md")
        ):
            rebuilt = KnowledgeService(settings, db=database).rebuild_from_bundle()
        return {
            "database": str(settings.database),
            "bundle": str(settings.bundle_dir),
            "rebuilt_concepts": rebuilt,
        }

    def status(self, context: WorkspaceContext) -> dict[str, Any]:
        database_path = context.company_database
        if database_path is None:
            return {"available": False, "warning": "company knowledge is disabled"}
        response: dict[str, Any] = {"available": database_path.is_file(), "database": str(database_path)}
        if not database_path.is_file():
            return {**response, "concepts": 0, "published": 0, "review": 0, "sources": 0, "jobs": 0}
        try:
            database = Database(database_path)
            with database.connect() as connection:
                response.update({
                    "concepts": int(connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]),
                    "published": int(connection.execute("SELECT COUNT(*) FROM concepts WHERE status='published'").fetchone()[0]),
                    "review": int(connection.execute("SELECT COUNT(*) FROM concepts WHERE status='review'").fetchone()[0]),
                    "sources": int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]),
                    "jobs": int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]),
                })
        except (sqlite3.Error, RuntimeError) as exc:
            response.update({"available": False, "warning": f"CKB database is unreadable: {exc}"})
        return response

    def search(self, context: WorkspaceContext, query: str, limit: int) -> dict[str, Any]:
        state = self.status(context)
        if not state.get("available"):
            return {
                "available": False,
                "evidence_sufficient": False,
                "insufficient_evidence": True,
                "results": [],
                "attested_results": [],
                "warning": state.get("warning", "company knowledge base is absent"),
            }
        if context.company_database is None:
            raise ValueError("company knowledge is disabled by this project's profile")
        database = Database(context.company_database)
        with database.connect() as connection:
            branch = connection.execute(
                "SELECT id FROM branches WHERE is_canonical=1 ORDER BY id LIMIT 1"
            ).fetchone()
        branch_id = int(branch["id"]) if branch is not None else None
        found = ckb_search(database, query, limit, lm_client=None, branch_id=branch_id)
        normalized: list[dict[str, Any]] = []
        attested_results: list[dict[str, Any]] = []
        with database.connect() as connection:
            for result in found.get("results", []):
                rows = connection.execute(
                    "SELECT c.id,c.text,c.confidence,c.document_checksum,c.source_uri,c.locator,c.excerpt,c.citations_json,c.verified,"
                    "d.checksum AS ingested_checksum,d.source_uri AS ingested_source_uri,"
                    "k.document_id AS document_id "
                    "FROM claims c JOIN concepts k ON k.id=c.concept_id "
                    "LEFT JOIN documents d ON d.id=k.document_id WHERE c.concept_id=? ORDER BY c.id",
                    (result["id"],),
                ).fetchall()
                claims: list[dict[str, Any]] = []
                for row in rows:
                    stored_citations, citations_well_formed = _citations(row)
                    citations = [
                        _verified_citation(
                            context,
                            connection,
                            row,
                            citation,
                            primary=index == 0,
                        )
                        for index, citation in enumerate(stored_citations)
                    ]
                    primary = citations[0] if citations else {}
                    sufficient = bool(
                        citations_well_formed
                        and citations
                        and all(bool(citation["verified"]) for citation in citations)
                    )
                    claims.append({
                        "id": int(row["id"]),
                        "text": row["text"],
                        "confidence": float(row["confidence"]),
                        "verified": sufficient,
                        "stored_verified": bool(row["verified"]),
                        "source_uri": primary.get("source_uri"),
                        "locator": primary.get("locator"),
                        "excerpt": primary.get("excerpt"),
                        "citations": citations,
                        "evidence_sufficient": sufficient,
                    })
                sufficient = bool(claims) and all(bool(claim["evidence_sufficient"]) for claim in claims)
                normalized.append({
                    "source": "company_knowledge",
                    "authority": "citation_backed_fact",
                    "id": result["id"],
                    "title": result["title"],
                    "type": result["type"],
                    "description": result.get("description"),
                    "body": _excerpt(result.get("body", ""), query, 2000),
                    "path": result.get("path"),
                    "tags": result.get("tags", []),
                    "quality": result.get("quality", {}),
                    "score": result.get("score", 0.0),
                    "channels": result.get("channels", []),
                    "claims": claims,
                    "evidence_sufficient": sufficient,
                })
            attested_rows = connection.execute(
                "SELECT id,type,title,description,body,path,tags_json,quality_json "
                "FROM concepts WHERE branch_id=? AND status='review' AND document_id IS NULL "
                "ORDER BY updated_at DESC LIMIT ?",
                (branch_id, max(50, limit * 20)),
            ).fetchall()
            query_tokens = _tokens(query)
            ranked_attested: list[tuple[float, sqlite3.Row]] = []
            folded_query = _fold(query)
            for row in attested_rows:
                searchable = " ".join(
                    str(row[key] or "") for key in ("title", "description", "body")
                )
                searchable_tokens = _tokens(searchable)
                overlap = len(query_tokens & searchable_tokens)
                if not overlap and folded_query not in _fold(searchable):
                    continue
                ranked_attested.append((overlap / max(1, len(query_tokens)), row))
            ranked_attested.sort(key=lambda item: item[0], reverse=True)
            for _, row in ranked_attested[:limit]:
                try:
                    tags = json.loads(row["tags_json"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    tags = []
                try:
                    quality = json.loads(row["quality_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    quality = {}
                attested_results.append({
                    "source": "company_knowledge",
                    "authority": "unverified_canonical_claim",
                    "status": "review",
                    "id": row["id"],
                    "title": row["title"],
                    "type": row["type"],
                    "description": row["description"],
                    "body": _excerpt(row["body"] or "", query, 1000),
                    "path": row["path"],
                    "tags": tags if isinstance(tags, list) else [],
                    "quality": quality if isinstance(quality, dict) else {},
                    "evidence_sufficient": False,
                    "requires_source_reingestion": True,
                })
        sufficient = bool(normalized) and all(
            bool(result["evidence_sufficient"]) for result in normalized
        )
        response: dict[str, Any] = {
            "available": True,
            "semantic_available": bool(found.get("semantic_available")),
            "evidence_sufficient": sufficient,
            "insufficient_evidence": not sufficient,
            "results": normalized,
            "attested_results": attested_results,
        }
        if normalized and not sufficient:
            response["warning"] = "company results lack complete verified citations"
        elif attested_results and not normalized:
            response["warning"] = "canonical Git history matched, but its sources must be re-ingested before factual use"
        elif not normalized:
            response["warning"] = "company knowledge base returned no supporting result"
        return response
