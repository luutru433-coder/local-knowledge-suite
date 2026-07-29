# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from local_knowledge.ckb.models import CitationLocator, ClaimDraft
from local_knowledge.ckb.okf import (
    append_log,
    quality_report,
    regenerate_indexes,
    render_concept,
    validate_bundle,
    validate_concept_text,
)


def cited_claim(confidence: float = 0.95) -> ClaimDraft:
    return ClaimDraft(
        "Weekly revenue is reported every Monday.",
        confidence,
        [CitationLocator("file:///policy.md", "lines 1-2", "Weekly revenue is reported every Monday.", "abc")],
    )


def test_rendered_concept_is_okf_conformant() -> None:
    markdown = render_concept(
        concept_type="Policy",
        title="Revenue Reporting",
        description="Weekly reporting policy.",
        tags=["finance", "en"],
        resource="file:///policy.md",
        claims=[cited_claim()],
    )
    assert validate_concept_text(markdown) == []
    assert "type: Policy" in markdown
    assert "# Citations" in markdown
    assert "[1]" in markdown


def test_quality_gate_boundaries() -> None:
    valid = [cited_claim() for _ in range(9)] + [ClaimDraft("Uncited", 0.95, [])]
    report = quality_report(valid, True, 0.90, 0.85, 0.90)
    assert report.coverage == 0.90
    assert report.publishable
    below = [cited_claim() for _ in range(8)] + [ClaimDraft("A", 0.95, []), ClaimDraft("B", 0.95, [])]
    assert not quality_report(below, True, 0.90, 0.85, 0.90).publishable
    low_confidence = [cited_claim(0.84), cited_claim(0.99)]
    assert not quality_report(low_confidence, True, 0.90, 0.85, 0.90).publishable


def test_indexes_logs_and_bundle_validation(tmp_path: Path) -> None:
    concept = tmp_path / "policies" / "revenue.md"
    concept.parent.mkdir(parents=True)
    concept.write_text(render_concept(
        concept_type="Policy", title="Revenue", description="Reporting.", tags=[], resource="file:///x", claims=[cited_claim()]
    ), encoding="utf-8")
    regenerate_indexes(tmp_path)
    append_log(tmp_path, "Creation", "policies/revenue.md")
    assert validate_bundle(tmp_path) == {}
    assert "[Revenue](revenue.md)" in (tmp_path / "policies" / "index.md").read_text(encoding="utf-8")


def test_invalid_concept_is_reported(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text("# No frontmatter\n", encoding="utf-8")
    failures = validate_bundle(tmp_path)
    assert "bad.md" in failures
