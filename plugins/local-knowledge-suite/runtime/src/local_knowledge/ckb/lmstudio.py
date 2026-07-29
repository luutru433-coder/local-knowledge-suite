# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .models import ParsedSection
from .network import canonicalize_lm_studio_url


class LMStudioError(RuntimeError):
    pass


class LMStudioClient:
    def __init__(self, base_url: str, chat_model: str, embedding_model: str, timeout: float = 120, bearer_token: str | None = None):
        self.base_url = canonicalize_lm_studio_url(base_url)
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.timeout = timeout
        self.bearer_token = bearer_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"} if self.bearer_token else {}

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(
            timeout=timeout,
            headers=self._headers(),
            follow_redirects=False,
            trust_env=False,
        )

    def health(self) -> dict[str, Any]:
        try:
            with self._client(10) as client:
                response = client.get(f"{self.base_url}/models")
                response.raise_for_status()
                models = [item.get("id") for item in response.json().get("data", [])]
                chat_ok = False
                embedding_ok = False
                chat_error = None
                embedding_error = None
                if self.chat_model in models:
                    try:
                        probe = client.post(
                            f"{self.base_url}/chat/completions",
                            json={"model": self.chat_model, "messages": [{"role": "user", "content": "Reply OK"}], "temperature": 0, "max_tokens": 2},
                        )
                        probe.raise_for_status()
                        chat_ok = bool(probe.json().get("choices"))
                    except (httpx.HTTPError, ValueError) as exc:
                        chat_error = str(exc)
                if self.embedding_model in models:
                    try:
                        probe = client.post(f"{self.base_url}/embeddings", json={"model": self.embedding_model, "input": ["health check"]})
                        probe.raise_for_status()
                        embedding_ok = bool(probe.json().get("data"))
                    except (httpx.HTTPError, ValueError) as exc:
                        embedding_error = str(exc)
            return {
                "reachable": True,
                "models": models,
                "chat_model_available": self.chat_model in models,
                "embedding_model_available": self.embedding_model in models,
                "chat_endpoint": chat_ok,
                "embedding_endpoint": embedding_ok,
                "chat_error": chat_error,
                "embedding_error": embedding_error,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {"reachable": False, "error": str(exc), "models": []}

    def extract_claims(self, title: str, language: str, sections: list[ParsedSection]) -> list[dict[str, Any]]:
        numbered = []
        for index, section in enumerate(sections):
            text = section.text
            numbered.append(f"SECTION {index} ({section.locator}; {section.title})\n{text}")
        prompt = f"""
Extract durable, atomic factual claims from this company source.
Preserve the source language ({language}). Do not infer facts that are not explicit.
Return JSON only with shape:
{{"claims":[{{"text":"...","confidence":0.0,"section_index":0,"excerpt":"exact supporting excerpt","entities":["entity name"]}}]}}
Each excerpt must be copied exactly from one section. Confidence must be between 0 and 1.
Prefer 3-20 high-value claims and omit navigation, signatures, and boilerplate.

TITLE: {title}

{chr(10).join(numbered)}
""".strip()
        payload = {
            "model": self.chat_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "You extract cited company knowledge and emit strict JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            with self._client(self.timeout) as client:
                response = client.post(f"{self.base_url}/chat/completions", json=payload)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise LMStudioError(f"LM Studio claim extraction failed: {exc}") from exc
        data = self._parse_json(content)
        claims = data.get("claims", [])
        if not isinstance(claims, list):
            raise LMStudioError("LM Studio response field 'claims' is not a list")
        return [item for item in claims if isinstance(item, dict)]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            with self._client(self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.embedding_model, "input": texts},
                )
                response.raise_for_status()
                rows = sorted(response.json()["data"], key=lambda item: item["index"])
            return [[float(value) for value in row["embedding"]] for row in rows]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise LMStudioError(f"LM Studio embedding failed: {exc}") from exc

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LMStudioError(f"LM Studio returned invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise LMStudioError("LM Studio response must be a JSON object")
        return data
