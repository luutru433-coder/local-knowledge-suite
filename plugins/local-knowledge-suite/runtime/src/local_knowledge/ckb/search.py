# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from typing import Any

from .db import Database
from .lmstudio import LMStudioClient, LMStudioError


def fold_vietnamese(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    folded = "".join(character for character in normalized if not unicodedata.combining(character))
    return folded.replace("\u0111", "d").replace("\u0110", "D").lower()


def _fts_query(query: str) -> str:
    phrases = re.findall(r'"([^"]+)"', query)
    remainder = re.sub(r'"[^"]+"', " ", query)
    tokens = re.findall(r"[^\W_]+", remainder, flags=re.UNICODE)
    parts = [f'"{phrase.replace(chr(34), "")}"' for phrase in phrases if phrase.strip()]
    parts.extend(f'"{token}"*' for token in tokens if token)
    return " OR ".join(parts)


def index_concept(db: Database, concept_id: str, title: str, body: str) -> None:
    folded = fold_vietnamese(f"{title}\n{body}")
    with db.transaction(immediate=True) as connection:
        connection.execute("DELETE FROM search_fts WHERE concept_id=?", (concept_id,))
        connection.execute(
            "INSERT INTO search_fts(concept_id,title,body,folded) VALUES(?,?,?,?)",
            (concept_id, title, body, folded),
        )


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def search(
    db: Database,
    query: str,
    limit: int,
    lm_client: LMStudioClient | None = None,
    concept_type: str | None = None,
    tags: list[str] | None = None,
    branch_id: int | None = None,
) -> dict[str, Any]:
    fts = _fts_query(query)
    folded_fts = _fts_query(fold_vietnamese(query))
    lexical_rows: list[Any] = []
    with db.connect() as connection:
        if fts or folded_fts:
            expression = " OR ".join(f"({part})" for part in (fts, folded_fts) if part)
            lexical_constraints = ["c.status='published'"]
            lexical_params: list[object] = [expression]
            if branch_id is not None:
                lexical_constraints.append("c.branch_id=?")
                lexical_params.append(branch_id)
            if concept_type is not None:
                lexical_constraints.append("c.type=?")
                lexical_params.append(concept_type)
            lexical_rows = connection.execute(
                "SELECT search_fts.concept_id, bm25(search_fts, 0.0, 2.0, 1.0, 1.5) AS score "
                "FROM search_fts JOIN concepts c ON c.id=search_fts.concept_id "
                f"WHERE search_fts MATCH ? AND {' AND '.join(lexical_constraints)} "
                "ORDER BY score LIMIT 200",
                tuple(lexical_params),
            ).fetchall()
        branch_clause = " AND branch_id=?" if branch_id is not None else ""
        params: tuple[object, ...] = (branch_id,) if branch_id is not None else ()
        concept_rows = connection.execute(
            "SELECT id,type,title,description,body,tags_json,path,quality_json,maturity,pagerank,endorsements,usage_count "
            f"FROM concepts WHERE status='published'{branch_clause}",
            params,
        ).fetchall()
        embedding_rows = connection.execute(
            "SELECT e.concept_id,e.vector_json FROM embeddings e JOIN concepts c ON c.id=e.concept_id "
            f"WHERE c.status='published'{branch_clause}",
            params,
        ).fetchall()
        chunk_embedding_rows = connection.execute(
            "SELECT c.concept_id,e.vector_json FROM chunk_embeddings e JOIN chunks c ON c.id=e.chunk_id "
            "JOIN concepts k ON k.id=c.concept_id WHERE c.concept_id IS NOT NULL AND k.status='published'"
            + (" AND k.branch_id=?" if branch_id is not None else ""),
            params,
        ).fetchall()
    concepts = {row["id"]: dict(row) for row in concept_rows}
    scores: defaultdict[str, float] = defaultdict(float)
    channels: defaultdict[str, list[str]] = defaultdict(list)
    for rank, row in enumerate(lexical_rows, 1):
        scores[row["concept_id"]] += 1 / (60 + rank)
        channels[row["concept_id"]].append("bm25")
    semantic_available = False
    if lm_client is not None and (embedding_rows or chunk_embedding_rows):
        try:
            query_vector = lm_client.embed([query])[0]
            best_similarity: dict[str, float] = {}
            for row in [*embedding_rows, *chunk_embedding_rows]:
                similarity = _cosine(query_vector, json.loads(row["vector_json"]))
                best_similarity[row["concept_id"]] = max(best_similarity.get(row["concept_id"], -1.0), similarity)
            ranked = sorted(best_similarity.items(), key=lambda item: item[1], reverse=True)[:200]
            semantic_available = True
            for rank, (concept_id, similarity) in enumerate(ranked, 1):
                if similarity <= 0:
                    continue
                scores[concept_id] += 1 / (60 + rank)
                channels[concept_id].append("semantic")
        except (LMStudioError, IndexError, json.JSONDecodeError):
            pass
    exact = query.strip().strip('"').casefold()
    results: list[dict[str, Any]] = []
    for concept_id, score in scores.items():
        concept = concepts.get(concept_id)
        if concept is None:
            continue
        if concept_type and concept["type"] != concept_type:
            continue
        concept_tags = json.loads(concept["tags_json"])
        if tags and not set(tags).issubset(concept_tags):
            continue
        haystack = f"{concept['title']}\n{concept['body']}".casefold()
        if exact and exact in haystack:
            score += 0.05
            channels[concept_id].append("exact")
        pagerank_factor = 0.5 + max(0.0, min(1.0, float(concept["pagerank"])))
        maturity_factor = max(0.1, min(1.0, float(concept["maturity"])))
        endorsement_factor = min(3.0, 1.0 + math.log1p(int(concept["endorsements"])))
        usage_factor = min(3.0, 1.0 + math.log1p(int(concept["usage_count"])))
        concept["retrieval_score"] = score
        concept["value_score"] = pagerank_factor * maturity_factor * endorsement_factor * usage_factor
        concept["score"] = score * concept["value_score"]
        concept["channels"] = sorted(set(channels[concept_id]))
        concept["tags"] = concept_tags
        concept["quality"] = json.loads(concept.pop("quality_json"))
        concept.pop("tags_json", None)
        results.append(concept)
    results.sort(key=lambda item: (item["score"], item["title"]), reverse=True)
    selected = results[:limit]
    return {"query": query, "semantic_available": semantic_available, "results": selected}


def recompute_value_graph(db: Database) -> None:
    with db.connect() as connection:
        concepts = [dict(row) for row in connection.execute("SELECT id,path,body FROM concepts WHERE status='published'")]
        entity_edges = connection.execute(
            "SELECT concept_id,entity_id FROM concept_entities WHERE concept_id IN (SELECT id FROM concepts WHERE status='published')"
        ).fetchall()
    if not concepts:
        return
    path_to_id = {str(row["path"]): str(row["id"]) for row in concepts if row.get("path")}
    graph: dict[str, set[str]] = {str(row["id"]): set() for row in concepts}
    internal_edges: set[tuple[str, str]] = set()
    for row in concepts:
        source_id = str(row["id"])
        source_path = str(row.get("path") or "")
        source_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
        for target in re.findall(r"\[[^\]]+\]\(([^)]+\.md)\)", str(row["body"]), flags=re.IGNORECASE):
            clean = target.split("#", 1)[0].lstrip("/")
            if clean.startswith("./"):
                clean = clean[2:]
            candidate = f"{source_dir}/{clean}" if source_dir and "/" not in clean else clean
            target_id = path_to_id.get(candidate) or path_to_id.get(clean)
            if target_id and target_id != source_id:
                graph[source_id].add(target_id)
                internal_edges.add((source_id, target_id))
    for edge in entity_edges:
        concept_id = str(edge["concept_id"])
        entity_node = f"entity:{edge['entity_id']}"
        graph.setdefault(entity_node, set()).add(concept_id)
        graph.setdefault(concept_id, set()).add(entity_node)
    nodes = list(graph)
    count = len(nodes)
    ranks = {node: 1.0 / count for node in nodes}
    damping = 0.85
    for _ in range(50):
        dangling = sum(ranks[node] for node in nodes if not graph[node]) / count
        updated = {node: (1.0 - damping) / count + damping * dangling for node in nodes}
        for source, targets in graph.items():
            if targets:
                share = damping * ranks[source] / len(targets)
                for target in targets:
                    updated[target] += share
        ranks = updated
    concept_values = [ranks[str(row["id"])] for row in concepts]
    minimum = min(concept_values)
    maximum = max(concept_values)

    def normalize(value: float) -> float:
        normalized = (value - minimum) / (maximum - minimum) if maximum > minimum else 1.0
        return max(0.0, min(1.0, normalized))

    with db.transaction(immediate=True) as connection:
        connection.execute("DELETE FROM concept_links")
        connection.executemany(
            "INSERT INTO concept_links(source_concept_id,target_concept_id) VALUES(?,?)",
            sorted(internal_edges),
        )
        connection.executemany(
            "UPDATE concepts SET pagerank=? WHERE id=?",
            [(normalize(ranks[str(row["id"])]), row["id"]) for row in concepts],
        )
        for node, value in ranks.items():
            if node.startswith("entity:"):
                connection.execute("UPDATE entities SET pagerank=? WHERE id=?", (normalize(value), int(node.split(":", 1)[1])))
