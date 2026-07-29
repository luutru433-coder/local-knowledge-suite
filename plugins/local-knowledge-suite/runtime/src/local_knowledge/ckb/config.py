# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
from ipaddress import ip_address
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..winio import reject_reparse_points
from .network import canonicalize_lm_studio_url


DEFAULT_CORS_ORIGINS: tuple[str, ...] = ()


def packaged_portal_dir() -> Path | None:
    """Return only the trusted portal shipped inside the installed runtime."""

    portal = Path(__file__).resolve().parents[1] / "portal"
    reject_reparse_points(portal, "packaged portal")
    return portal if (portal / "index.html").is_file() else None


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _developer_cors_origins(value: str | None) -> tuple[str, ...]:
    origins: list[str] = []
    for raw_origin in (value or "").split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("CKB_CORS_ORIGINS contains an invalid port") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.hostname is None
            or port == 0
        ):
            raise ValueError(
                "CKB_CORS_ORIGINS must contain only HTTP(S) loopback origins"
            )
        hostname = parsed.hostname
        if hostname.casefold() != "localhost":
            try:
                if not ip_address(hostname).is_loopback:
                    raise ValueError
            except ValueError as exc:
                raise ValueError(
                    "CKB_CORS_ORIGINS must contain only HTTP(S) loopback origins"
                ) from exc
        normalized = origin[:-1] if origin.endswith("/") else origin
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


@dataclass(slots=True)
class Settings:
    root: Path
    data_dir: Path
    database: Path
    bundle_dir: Path
    portal_dir: Path | None = None
    lm_studio_url: str = "http://127.0.0.1:1234/v1"
    chat_model: str = "local-chat-model"
    embedding_model: str = "local-embedding-model"
    coverage_threshold: float = 0.90
    minimum_claim_confidence: float = 0.85
    average_claim_confidence: float = 0.90
    session_hours: int = 12
    crawler_user_agent: str = "LocalKnowledgeSuite/1.0"
    crawler_max_depth: int = 2
    crawler_max_pages: int = 100
    crawler_delay_seconds: float = 0.5
    crawler_max_bytes: int = 5_000_000
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    auto_publish: bool = True
    secure_cookies: bool = False
    canonical_branch: str = "main"
    lease_seconds: int = 300
    heartbeat_seconds: int = 60
    claim_batch_chars: int = 32000
    claim_batch_sections: int = 20
    keyring_service: str = "company-knowledge-base"

    def __post_init__(self) -> None:
        self.lm_studio_url = canonicalize_lm_studio_url(self.lm_studio_url)
        self.cors_origins = _developer_cors_origins(
            ",".join(self.cors_origins)
        )

    @classmethod
    def load(cls, root: str | Path | None = None) -> "Settings":
        project_root = Path(root or os.environ.get("CKB_ROOT") or Path.cwd()).resolve()
        from .gitops import (
            COMPANY_PRIVATE_TRACKED_PATHS,
            reject_tracked_private_paths,
        )

        reject_tracked_private_paths(
            project_root,
            COMPANY_PRIVATE_TRACKED_PATHS,
            label="company repository",
            require_own_repository=False,
        )
        reject_reparse_points(project_root / ".local-knowledge", "company .local-knowledge directory")
        reject_reparse_points(project_root / ".ckb", "company database store")
        reject_reparse_points(project_root / "knowledge", "company knowledge store")
        # Storage paths are deliberately derived from the explicit root. Process-wide
        # CKB_DATABASE/CKB_DATA_DIR overrides are unsafe when one MCP serves many projects.
        data_dir = (project_root / ".ckb").resolve()
        bundle_dir = (project_root / "knowledge").resolve()
        portal_dir = packaged_portal_dir()
        config_path = data_dir / "config.json"
        file_values: dict[str, object] = {}
        if config_path.exists():
            file_values = json.loads(config_path.read_text(encoding="utf-8"))
        origins = os.environ.get("CKB_CORS_ORIGINS")
        keyring_service = str(file_values.get("keyring_service", "company-knowledge-base"))
        try:
            from ..manifests import CompanyManifest

            company = CompanyManifest.load(project_root)
            keyring_service = f"local-knowledge-suite/{company.company_id}"
        except Exception:
            # Standalone `ckb` compatibility remains available for legacy repositories.
            pass
        return cls(
            root=project_root,
            data_dir=data_dir,
            database=(data_dir / "ckb.sqlite3").resolve(),
            bundle_dir=bundle_dir,
            portal_dir=portal_dir,
            lm_studio_url=os.environ.get(
                "CKB_LM_STUDIO_URL",
                str(file_values.get("lm_studio_url", "http://127.0.0.1:1234/v1")),
            ),
            chat_model=os.environ.get("CKB_CHAT_MODEL", str(file_values.get("chat_model", "local-chat-model"))),
            embedding_model=os.environ.get("CKB_EMBEDDING_MODEL", str(file_values.get("embedding_model", "local-embedding-model"))),
            coverage_threshold=float(os.environ.get("CKB_COVERAGE_THRESHOLD", file_values.get("coverage_threshold", 0.90))),
            minimum_claim_confidence=float(os.environ.get("CKB_MIN_CLAIM_CONFIDENCE", file_values.get("minimum_claim_confidence", 0.85))),
            average_claim_confidence=float(os.environ.get("CKB_AVG_CLAIM_CONFIDENCE", file_values.get("average_claim_confidence", 0.90))),
            session_hours=int(os.environ.get("CKB_SESSION_HOURS", file_values.get("session_hours", 12))),
            crawler_user_agent=os.environ.get(
                "CKB_CRAWLER_USER_AGENT",
                str(
                    file_values.get(
                        "crawler_user_agent",
                        "LocalKnowledgeSuite/1.0",
                    )
                ),
            ),
            crawler_max_depth=int(os.environ.get("CKB_CRAWLER_MAX_DEPTH", file_values.get("crawler_max_depth", 2))),
            crawler_max_pages=int(os.environ.get("CKB_CRAWLER_MAX_PAGES", file_values.get("crawler_max_pages", 100))),
            crawler_delay_seconds=float(os.environ.get("CKB_CRAWLER_DELAY", file_values.get("crawler_delay_seconds", 0.5))),
            crawler_max_bytes=int(os.environ.get("CKB_CRAWLER_MAX_BYTES", file_values.get("crawler_max_bytes", 5_000_000))),
            # Cross-origin credential sharing is an explicit process-local
            # developer override. Persisted values from older configs are
            # deliberately ignored.
            cors_origins=_developer_cors_origins(origins),
            auto_publish=_bool(os.environ.get("CKB_AUTO_PUBLISH"), bool(file_values.get("auto_publish", True))),
            secure_cookies=_bool(os.environ.get("CKB_SECURE_COOKIES"), bool(file_values.get("secure_cookies", False))),
            canonical_branch=os.environ.get("CKB_CANONICAL_BRANCH", str(file_values.get("canonical_branch", "main"))),
            lease_seconds=int(os.environ.get("CKB_LEASE_SECONDS", file_values.get("lease_seconds", 300))),
            heartbeat_seconds=int(os.environ.get("CKB_HEARTBEAT_SECONDS", file_values.get("heartbeat_seconds", 60))),
            claim_batch_chars=int(os.environ.get("CKB_CLAIM_BATCH_CHARS", file_values.get("claim_batch_chars", 32000))),
            claim_batch_sections=int(os.environ.get("CKB_CLAIM_BATCH_SECTIONS", file_values.get("claim_batch_sections", 20))),
            keyring_service=keyring_service,
        )

    @classmethod
    def for_company(cls, root: str | Path, company_id: str) -> "Settings":
        settings = cls.load(root)
        settings.keyring_service = f"local-knowledge-suite/{company_id}"
        return settings

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        (self.root / ".local-sources").mkdir(parents=True, exist_ok=True)

    def write_user_config(self) -> Path:
        self.ensure_directories()
        path = self.data_dir / "config.json"
        payload = asdict(self)
        for key in (
            "root",
            "data_dir",
            "database",
            "bundle_dir",
            "portal_dir",
            "cors_origins",
        ):
            payload.pop(key, None)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path
