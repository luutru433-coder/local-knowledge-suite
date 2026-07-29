# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml

from .models import ClaimDraft, QualityReport
from ..winio import replace_file


RESERVED = {"index.md", "log.md"}


def slugify(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in folded if not unicodedata.combining(ch))
    ascii_value = ascii_value.replace("\u0111", "d").replace("\u0110", "D").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug[:80] or "concept"


def render_concept(
    *,
    concept_type: str,
    title: str,
    description: str,
    tags: list[str],
    resource: str,
    claims: list[ClaimDraft],
    body_override: str | None = None,
) -> str:
    structured_claims = [
        {
            "text": claim.text,
            "confidence": claim.confidence,
            "verified": bool(claim.citations),
            "citations": [asdict(citation) for citation in claim.citations],
            "entities": list(claim.entities),
        }
        for claim in claims
    ]
    frontmatter = {
        "okf_schema_version": 2,
        "type": concept_type,
        "title": title,
        "description": description,
        "resource": resource,
        "tags": tags,
        "timestamp": datetime.now(UTC).isoformat(),
        "claims": structured_claims,
    }
    body = body_override.strip() if body_override else "\n\n".join(f"- {claim.text} [{index}]" for index, claim in enumerate(claims, 1))
    citation_lines: list[str] = []
    for index, claim in enumerate(claims, 1):
        if not claim.citations:
            continue
        citation = claim.citations[0]
        label = f"{citation.source_uri} \u2014 {citation.locator}"
        target = citation.source_uri.replace(" ", "%20")
        citation_lines.append(f"[{index}] [{label}]({target})")
    citations = "\n".join(citation_lines)
    suffix = f"\n\n# Citations\n\n{citations}" if citations else ""
    canonical_body = f"# {title}\n\n{body}{suffix}\n"
    frontmatter["evidence_sha256"] = concept_evidence_sha256(canonical_body, structured_claims)
    yaml_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{yaml_text}\n---\n\n{canonical_body}"


def concept_evidence_sha256(body: str, claims: object) -> str:
    payload = json.dumps(
        {"body": body, "claims": claims},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def concept_integrity_valid(metadata: dict[str, object], body: str) -> bool:
    claims = metadata.get("claims")
    recorded = metadata.get("evidence_sha256")
    if not isinstance(claims, list) or not isinstance(recorded, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded):
        return False
    try:
        expected = concept_evidence_sha256(body, claims)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(recorded, expected)


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        raise ValueError("concept must start with YAML frontmatter")
    try:
        _, raw, body = text.split("---", 2)
    except ValueError as exc:
        raise ValueError("frontmatter closing delimiter is missing") from exc
    metadata = yaml.safe_load(raw) or {}
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter must be a mapping")
    return metadata, body.lstrip("\r\n")


def set_concept_title(text: str, title: str) -> str:
    metadata, body = parse_frontmatter(text)
    metadata["title"] = title
    body = re.sub(r"^#\s+.*$", f"# {title}", body, count=1, flags=re.MULTILINE)
    body = body.rstrip() + "\n"
    metadata["evidence_sha256"] = concept_evidence_sha256(body, metadata.get("claims", []))
    yaml_text = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{yaml_text}\n---\n\n{body}"


def validate_concept_text(text: str) -> list[str]:
    errors: list[str] = []
    try:
        metadata, body = parse_frontmatter(text)
    except (ValueError, yaml.YAMLError) as exc:
        return [str(exc)]
    if not isinstance(metadata.get("type"), str) or not str(metadata["type"]).strip():
        errors.append("frontmatter type must be a non-empty string")
    if not concept_integrity_valid(metadata, body):
        errors.append("frontmatter evidence_sha256 is missing or does not match body and structured claims")
    return errors


def validate_index(text: str, *, root: bool = False) -> list[str]:
    if text.startswith("---\n") and not root:
        return ["non-root index.md must not contain frontmatter"]
    return []


def validate_log(text: str) -> list[str]:
    errors: list[str] = []
    for heading in re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", heading.strip()):
            errors.append(f"log date heading is not ISO YYYY-MM-DD: {heading}")
    return errors


def validate_bundle(bundle_dir: str | Path) -> dict[str, list[str]]:
    root = Path(bundle_dir)
    failures: dict[str, list[str]] = {}
    for path in root.rglob("*.md"):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.name == "index.md":
            errors = validate_index(text, root=path.parent == root)
        elif path.name == "log.md":
            errors = validate_log(text)
        else:
            errors = validate_concept_text(text)
        if errors:
            failures[relative] = errors
    return failures


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def regenerate_indexes(bundle_dir: str | Path) -> list[Path]:
    root = Path(bundle_dir)
    changed: list[Path] = []
    directories = {root, *(p.parent for p in root.rglob("*.md"))}
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        entries: list[str] = []
        for child in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.is_dir() and any(child.rglob("*.md")):
                entries.append(f"* [{child.name}]({child.name}/) - Knowledge group")
            elif child.suffix == ".md" and child.name not in RESERVED:
                metadata, _ = parse_frontmatter(child.read_text(encoding="utf-8"))
                title = str(metadata.get("title") or child.stem.replace("-", " ").title())
                description = str(metadata.get("description") or "")
                entries.append(f"* [{title}]({child.name}) - {description}".rstrip(" -"))
        content = "# Knowledge Index\n\n" + ("\n".join(entries) if entries else "No concepts yet.") + "\n"
        index_path = directory / "index.md"
        if not index_path.exists() or index_path.read_text(encoding="utf-8") != content:
            atomic_write(index_path, content)
            changed.append(index_path)
    return changed


def append_log(bundle_dir: str | Path, action: str, concept_path: str) -> Path:
    path = Path(bundle_dir) / "log.md"
    today = datetime.now(UTC).date().isoformat()
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Knowledge Update Log\n"
    entry = f"* **{action}**: [{PurePosixPath(concept_path).stem}](/${concept_path})".replace("/$", "/")
    heading = f"## {today}"
    if heading in existing:
        content = existing.replace(heading, f"{heading}\n{entry}", 1)
    else:
        content = f"# Knowledge Update Log\n\n{heading}\n{entry}\n" + existing.removeprefix("# Knowledge Update Log\n").lstrip()
    atomic_write(path, content.rstrip() + "\n")
    return path


def quality_report(
    claims: list[ClaimDraft],
    okf_valid: bool,
    coverage_threshold: float,
    minimum_threshold: float,
    average_threshold: float,
) -> QualityReport:
    count = len(claims)
    cited = sum(bool(claim.citations) for claim in claims)
    coverage = cited / count if count else 0.0
    confidences = [claim.confidence for claim in claims]
    minimum = min(confidences, default=0.0)
    average = sum(confidences) / count if count else 0.0
    reasons: list[str] = []
    if count == 0:
        reasons.append("no factual claims were extracted")
    if coverage < coverage_threshold:
        reasons.append(f"citation coverage {coverage:.1%} is below {coverage_threshold:.1%}")
    if minimum < minimum_threshold:
        reasons.append(f"minimum confidence {minimum:.2f} is below {minimum_threshold:.2f}")
    if average < average_threshold:
        reasons.append(f"average confidence {average:.2f} is below {average_threshold:.2f}")
    if not okf_valid:
        reasons.append("generated concept is not OKF conformant")
    return QualityReport(count, cited, coverage, minimum, average, okf_valid, not reasons, reasons)


def quality_to_json(report: QualityReport) -> str:
    return json.dumps({
        "claim_count": report.claim_count,
        "cited_claim_count": report.cited_claim_count,
        "coverage": report.coverage,
        "minimum_confidence": report.minimum_confidence,
        "average_confidence": report.average_confidence,
        "okf_valid": report.okf_valid,
        "publishable": report.publishable,
        "reasons": report.reasons,
    }, ensure_ascii=False)
