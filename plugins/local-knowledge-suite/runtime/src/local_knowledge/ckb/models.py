# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


Role = Literal["admin", "reviewer", "reader"]
SourceKind = Literal["file", "folder", "website"]


class SourceCreate(BaseModel):
    kind: SourceKind
    uri: str = Field(min_length=1)
    title: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    branch: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,64}$")
    password: str = Field(min_length=12)
    role: Role


class FeedbackCreate(BaseModel):
    query: str = Field(min_length=1)
    details: str = ""
    concept_id: str | None = None


class FeedbackUpdate(BaseModel):
    status: Literal["open", "resolved"]


class ReviewDecision(BaseModel):
    decision: Literal["approve", "reject"]
    edited_title: str | None = None
    edited_body: str | None = None


class ClaimRevision(BaseModel):
    text: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class BranchMemberUpdate(BaseModel):
    user_id: int
    role: Role


class SecretSet(BaseModel):
    value: str = Field(min_length=1)


class GitCredentialSet(BaseModel):
    username: str = Field(min_length=1)
    token: str = Field(min_length=1)


@dataclass(slots=True)
class CitationLocator:
    source_uri: str
    locator: str
    excerpt: str
    checksum: str


@dataclass(slots=True)
class ClaimDraft:
    text: str
    confidence: float
    citations: list[CitationLocator] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedSection:
    locator: str
    title: str
    text: str


@dataclass(slots=True)
class SourceDocument:
    source_uri: str
    title: str
    media_type: str
    checksum: str
    language: str
    sections: list[ParsedSection]


@dataclass(slots=True)
class QualityReport:
    claim_count: int
    cited_claim_count: int
    coverage: float
    minimum_confidence: float
    average_confidence: float
    okf_valid: bool
    publishable: bool
    reasons: list[str] = field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=100)
    concept_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    branch: str | None = None
