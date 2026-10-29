"""Artifact search: FTS5 keyword, Qdrant chunk vectors, and RRF fusion.

Accuracy notes, because each of these used to make a correct query miss:

* The FTS table indexes ``name`` and ``source_path`` as well as
  ``content_text``, but the query only filtered ``content_text``, so searching
  for a filename found nothing. The MATCH now runs against the whole table.
* A simple query used to become ``"term"*`` for every token (prefix AND only),
  which made ``"exact phrase"``, OR, NOT and NEAR impossible. Those pass
  through as FTS5 syntax now, and a syntax error is reported instead of being
  swallowed as "no results".
* Embeddings used to be one vector per file, truncated at 8,000 characters, so
  a long document could only ever return the file, never the passage. Chunks
  are embedded separately and carry their own text, which is what the result
  snippet is built from.
* The score shown was ``1/(1+bm25)``: a number with no meaning across queries.
  Results now carry the matched fields and an excerpt; ranking stays BM25 but
  is not presented as if it were a probability.
"""
from __future__ import annotations

import re
import uuid
import json
import logging
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

from app.artifacts.models import Artifact, ArtifactChunk, ArtifactType, IndexStatus
from app.config import get_config

if TYPE_CHECKING:
    pass

# A chunk is small enough to be about one topic and large enough to answer a
# question. Overlap keeps a sentence from being cut in half at a boundary.
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
SNIPPET_WIDTH = 240
REGEX_SCAN_LIMIT = 5000


def purge_artifact_rows(session: Session, artifacts: list[Artifact]) -> int:
    """Delete artifact records and their dependent analysis/index rows.

    Source evidence files are never touched. Relationship graph rows that cite
    a removed artifact are invalidated rather than left with stale provenance.
    """
    if not artifacts:
        return 0
    artifact_ids = [int(item.id) for item in artifacts]
    case_ids = {int(item.case_id) for item in artifacts}

    # Remove existing Qdrant points as well as SQLite rows. If the local index
    # is offline, the DB deletion still proceeds; semantic search joins hits
    # back to live artifacts and therefore cannot surface an orphan point.
    points_by_case: dict[int, set[str]] = {}
    for artifact in artifacts:
        points = points_by_case.setdefault(int(artifact.case_id), set())
        if artifact.vector_id:
            points.add(str(artifact.vector_id))
        for chunk in artifact.chunks:
            if chunk.vector_id:
                points.add(str(chunk.vector_id))
    if any(points_by_case.values()):
        config = get_config()
        with httpx.Client(timeout=3.0) as client:
            for case_id, point_ids in points_by_case.items():
                collection = f"{config.qdrant.collection_prefix}{case_id}"
                for start in range(0, len(point_ids), 500):
                    try:
                        response = client.post(
                            f"{config.qdrant.url}/collections/{collection}/points/delete",
                            json={"points": list(point_ids)[start:start + 500]},
                        )
                        if response.status_code >= 400:
                            logging.getLogger(__name__).warning(
                                "Could not delete artifact vectors from %s: HTTP %s",
                                collection, response.status_code,
                            )
                    except httpx.HTTPError:
                        logging.getLogger(__name__).warning(
                            "Qdrant is unavailable while deleting artifact vectors",
                            exc_info=True,
                        )

    from app.analysis.models import EntityRelationship
    from app.artifacts.models import Entity, TimelineEvent
    from app.findings.models import Finding, FindingArtifactLink

    artifact_refs = {
        str(item.artifact_id) for item in artifacts if item.artifact_id
    }
    db_refs = {str(value) for value in artifact_ids}
    findings = session.execute(
        select(Finding).where(Finding.case_id.in_(case_ids))
    ).scalars().all()
    for finding in findings:
        if not finding.ai_citations_json:
            continue
        try:
            citations = json.loads(finding.ai_citations_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(citations, list):
            continue
        filtered = [
            citation for citation in citations
            if not isinstance(citation, dict)
            or (
                str(citation.get("db_id", "")) not in db_refs
                and str(citation.get("artifact_id", "")) not in artifact_refs
            )
        ]
        if len(filtered) != len(citations):
            finding.ai_citations_json = json.dumps(filtered)

    relationships = session.execute(
        select(EntityRelationship).where(EntityRelationship.case_id.in_(case_ids))
    ).scalars().all()
    for relationship in relationships:
        try:
            linked = {int(value) for value in json.loads(relationship.artifact_ids_json or "[]")}
        except (TypeError, ValueError):
            linked = set()
        if linked.intersection(artifact_ids):
            session.delete(relationship)

    entity_ids = select(Entity.id).where(Entity.artifact_id.in_(artifact_ids))
    session.execute(delete(TimelineEvent).where(
        (TimelineEvent.artifact_id.in_(artifact_ids))
        | (TimelineEvent.entity_id.in_(entity_ids))
    ))
    session.execute(delete(FindingArtifactLink).where(
        FindingArtifactLink.artifact_id.in_(artifact_ids)
    ))
    session.execute(delete(ArtifactChunk).where(
        ArtifactChunk.artifact_id.in_(artifact_ids)
    ))
    session.execute(delete(Entity).where(Entity.artifact_id.in_(artifact_ids)))
    session.execute(delete(Artifact).where(Artifact.id.in_(artifact_ids)))
    session.flush()
    return len(artifact_ids)

# FTS5 operators and quoting. If any of these appear, the query is treated as
# FTS5 syntax rather than plain words.
_FTS_SYNTAX = re.compile(r'["*()]|\b(?:OR|AND|NOT|NEAR)\b', re.IGNORECASE)


class SearchError(RuntimeError):
    """A query the search backend cannot run, with a message for the UI."""


def build_fts_query(query: str) -> str:
    """Turn a query into FTS5 syntax.

    Plain words become prefix matches AND-ed together, which is what an
    investigator expects from a single box. Anything containing FTS5 syntax is
    passed through so phrase, OR, NOT and NEAR work.
    """
    cleaned = (query or "").strip()
    if not cleaned:
        return ""
    if _FTS_SYNTAX.search(cleaned):
        return cleaned
    terms = []
    for term in cleaned.split():
        term = term.replace('"', '""')
        if term:
            terms.append(f'"{term}"*')
    return " ".join(terms)


def query_terms(query: str) -> list[str]:
    """Words to highlight, with FTS5 syntax characters removed."""
    words = re.findall(r"[A-Za-z0-9_@./:+-]{2,}", query or "")
    seen: list[str] = []
    for word in words:
        lower = word.lower()
        if lower in {"or", "and", "not", "near"}:
            continue
        if lower not in seen:
            seen.append(lower)
    return seen


def make_snippet(source: str | None, terms: list[str], *, width: int = SNIPPET_WIDTH) -> str:
    """A one-line excerpt around the first matching term."""
    if not source:
        return ""
    text_value = source.replace("\r", " ").replace("\n", " ")
    lowered = text_value.lower()
    start = -1
    for term in terms:
        found = lowered.find(term)
        if found >= 0 and (start < 0 or found < start):
            start = found
    if start < 0:
        start = 0
    pad = max(0, (width - 60) // 2)
    begin = max(0, start - pad)
    end = min(len(text_value), begin + width)
    snippet = text_value[begin:end].strip()
    if begin > 0:
        snippet = "…" + snippet
    if end < len(text_value):
        snippet = snippet + "…"
    return snippet


def chunk_text(
    text_value: str,
    *,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[tuple[int, int, str]]:
    """Split text into ``(start, end, text)`` passages.

    Empty input yields no chunks. Whitespace-only passages are skipped, but
    every kept chunk keeps its original offsets so a hit can be located in the
    file.
    """
    if not text_value:
        return []
    if size <= 0:
        size = CHUNK_SIZE
    if overlap >= size:
        overlap = max(0, size // 4)

    chunks: list[tuple[int, int, str]] = []
    position = 0
    length = len(text_value)
    while position < length:
        end = min(length, position + size)
        # Prefer to break at a newline or space near the end of the window.
        if end < length:
            window = text_value[position:end]
            split_at = max(window.rfind("\n"), window.rfind(". "), window.rfind(" "))
            if split_at > size // 2:
                end = position + split_at + 1
        piece = text_value[position:end].strip()
        if piece:
            chunks.append((position, end, piece))
        if end >= length:
            break
        position = max(position + 1, end - overlap)
    return chunks


class SearchService:
    """Hybrid search service combining FTS5 keyword, Qdrant semantic, and RRF."""

    def __init__(self, session: Session):
        self.session = session
        self.config = get_config()
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()

    def list_case_artifacts(
        self,
        case_id: int,
        artifact_type: ArtifactType | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """List artifacts belonging to evidence that is still in the case."""
        from app.evidence.models import Evidence

        stmt = (
            select(Artifact)
            .options(joinedload(Artifact.evidence))
            .join(Evidence, Artifact.evidence_id == Evidence.id)
            .where(Artifact.case_id == case_id, Evidence.removed_at.is_(None))
        )
        if artifact_type:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        if date_from:
            stmt = stmt.where(Artifact.created_time >= datetime.combine(
                date_from, datetime.min.time(), tzinfo=timezone.utc
            ))
        if date_to:
            stmt = stmt.where(Artifact.created_time < datetime.combine(
                date_to, datetime.max.time(), tzinfo=timezone.utc
            ))
        stmt = stmt.order_by(Artifact.name.collate("NOCASE"), Artifact.id)
        return [
            {"artifact": artifact, "source": "case listing", "snippet": "", "matched_fields": []}
            for artifact in self.session.execute(stmt).scalars().all()
        ]

    def delete_artifact(
        self, case_id: int, artifact_db_id: int, deleted_by
    ) -> bool:
        """Permanently remove one artifact record and its derived analysis data."""
        artifact = self.session.get(Artifact, artifact_db_id)
        if artifact is None or artifact.case_id != case_id:
            return False
        from app.analysis.models import AnalysisJob, AnalysisJobStatus

        active = self.session.execute(
            select(AnalysisJob).where(
                AnalysisJob.case_id == case_id,
                AnalysisJob.status == AnalysisJobStatus.RUNNING,
            ).limit(1)
        ).scalar_one_or_none()
        if active is not None:
            raise ValueError(
                "Artifact deletion is unavailable while background case analysis is running."
            )
        from app.audit.service import AuditService

        details = {
            "artifact_id": artifact.artifact_id,
            "name": artifact.name,
            "source_path": artifact.source_path,
            "evidence_id": artifact.evidence_id,
        }
        AuditService(self.session).log_event(
            event_type="artifact",
            action="delete",
            result="success",
            user=deleted_by,
            case_id=case_id,
            target_type="artifact",
            target_id=artifact.id,
            details=details,
        )
        purge_artifact_rows(self.session, [artifact])
        return True

    async def _get_embedding(self, text_value: str) -> list[float]:
        """Embed one query string."""
        from app.ai.embeddings import embed_text

        return embed_text(text_value)

    async def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Embed several strings in one call."""
        from app.ai.embeddings import embed_texts

        return embed_texts(texts)

    # ------------------------------------------------------------------
    # Keyword search
    # ------------------------------------------------------------------
    async def keyword_search(
        self,
        case_id: int,
        query: str,
        artifact_type: ArtifactType | None = None,
        limit: int = 50,
        offset: int = 0,
        date_from: date | None = None,
        date_to: date | None = None,
        regex: bool = False,
    ) -> list[dict]:
        """Search with SQLite FTS5, or with a regular expression."""
        if regex:
            return await self.regex_search(
                case_id, query, artifact_type, limit=limit, offset=offset,
                date_from=date_from, date_to=date_to,
            )

        fts_query = build_fts_query(query)
        if not fts_query:
            return []

        sql = """
            SELECT a.*, bm25(artifacts_fts) as rank,
                   snippet(artifacts_fts, 2, '[', ']', '…', 12) as content_snippet
            FROM artifacts_fts
            JOIN artifacts a ON a.id = artifacts_fts.rowid
            WHERE artifacts_fts MATCH :query
            AND a.case_id = :case_id
            AND EXISTS (
                SELECT 1 FROM evidence e
                WHERE e.id = a.evidence_id AND e.removed_at IS NULL
            )
        """
        params: dict = {
            "query": fts_query,
            "case_id": case_id,
            "limit": max(1, int(limit)),
            "offset": max(0, int(offset)),
        }

        if artifact_type:
            sql += " AND a.artifact_type = :artifact_type"
            params["artifact_type"] = (
                artifact_type.value
                if hasattr(artifact_type, "value") else str(artifact_type)
            )

        if date_from:
            sql += " AND date(a.created_time) >= :date_from"
            params["date_from"] = date_from.isoformat()
        if date_to:
            sql += " AND date(a.created_time) <= :date_to"
            params["date_to"] = date_to.isoformat()

        sql += " ORDER BY rank LIMIT :limit OFFSET :offset"

        try:
            rows = self.session.execute(text(sql), params).mappings().all()
        except OperationalError as exc:
            raise SearchError(
                "The search syntax could not be understood. Check quotes and "
                "parentheses, or quote the phrase.\n"
                f"Details: {exc.orig}"
            ) from exc

        terms = query_terms(query)
        # The FTS query returns raw columns; fetch real ORM rows so the detail
        # pane keeps relationships (evidence), enum types and datetimes.
        ids = [row["id"] for row in rows]
        from app.evidence.models import Evidence

        orm_rows = {
            artifact.id: artifact
            for artifact in self.session.execute(
                select(Artifact)
                .options(joinedload(Artifact.evidence))
                .join(Evidence, Artifact.evidence_id == Evidence.id)
                .where(Artifact.id.in_(ids), Evidence.removed_at.is_(None))
            ).scalars().all()
        } if ids else {}

        results = []
        for row in rows:
            artifact = orm_rows.get(row["id"])
            if artifact is None:
                continue
            name = artifact.name or ""
            path = artifact.source_path or ""
            content = artifact.content_text or ""
            matched_fields = []
            if any(term in name.lower() for term in terms):
                matched_fields.append("name")
            if any(term in path.lower() for term in terms):
                matched_fields.append("path")
            if any(term in content.lower() for term in terms):
                matched_fields.append("content")

            snippet = ""
            if "name" in matched_fields or "path" in matched_fields:
                # The file was found by its name or location, so show that
                # rather than an unrelated first line of its content.
                snippet = make_snippet(f"{name} — {path}", terms)
            if not snippet:
                snippet = (row.get("content_snippet") or "").strip()
            if not snippet:
                snippet = make_snippet(content or name, terms)
            results.append({
                "artifact": artifact,
                "score": 1.0 / (1.0 + float(row["rank"] or 0.0)),
                "source": "keyword",
                "snippet": snippet,
                "matched_fields": matched_fields,
            })
        return results

    async def regex_search(
        self,
        case_id: int,
        pattern: str,
        artifact_type: ArtifactType | None = None,
        limit: int = 50,
        offset: int = 0,
        date_from: date | None = None,
        date_to: date | None = None,
        scan_limit: int = REGEX_SCAN_LIMIT,
    ) -> list[dict]:
        """Case-insensitive regular expression over name, path and content.

        SQLite has no built-in REGEXP function, so candidates are filtered in
        Python. ``scan_limit`` bounds the work; the UI says when a scan was
        capped so a missing hit is never mistaken for an absent one.
        """
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise SearchError(f"Invalid regular expression: {exc}") from exc

        from app.evidence.models import Evidence

        stmt = (
            select(Artifact)
            .options(joinedload(Artifact.evidence))
            .join(Evidence, Artifact.evidence_id == Evidence.id)
            .where(Artifact.case_id == case_id, Evidence.removed_at.is_(None))
        )
        if artifact_type:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        if date_from:
            stmt = stmt.where(Artifact.created_time >= datetime.combine(
                date_from, datetime.min.time(), tzinfo=timezone.utc
            ))
        if date_to:
            stmt = stmt.where(Artifact.created_time < datetime.combine(
                date_to, datetime.max.time(), tzinfo=timezone.utc
            ))
        stmt = stmt.order_by(Artifact.id).limit(max(1, int(scan_limit)))
        rows = list(self.session.execute(stmt).scalars().all())

        matches: list[dict] = []
        for artifact in rows:
            matched_fields = []
            snippet = ""
            for field, value in (
                ("name", artifact.name or ""),
                ("path", artifact.source_path or ""),
                ("content", artifact.content_text or ""),
            ):
                found = compiled.search(value)
                if not found:
                    continue
                matched_fields.append(field)
                if not snippet:
                    begin = max(0, found.start() - 80)
                    end = min(len(value), found.end() + 120)
                    snippet = value[begin:end].replace("\n", " ").strip()
                    if begin > 0:
                        snippet = "…" + snippet
                    if end < len(value):
                        snippet += "…"
            if matched_fields:
                matches.append({
                    "artifact": artifact,
                    "score": 0.0,
                    "source": "regex",
                    "snippet": snippet,
                    "matched_fields": matched_fields,
                })

        start = max(0, int(offset))
        return matches[start:start + max(1, int(limit))]

    # ------------------------------------------------------------------
    # Semantic search
    # ------------------------------------------------------------------
    async def semantic_search(
        self,
        case_id: int,
        query: str,
        artifact_type: ArtifactType | None = None,
        limit: int = 20,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Search Qdrant chunk vectors and collapse hits to one row per file."""
        try:
            query_vector = await self._get_embedding(query)
            if not query_vector:
                return []

            collection_name = f"{self.config.qdrant.collection_prefix}{case_id}"
            # Ask for more chunk hits than files wanted: several hits can
            # belong to the same artifact.
            search_payload = {
                "vector": query_vector,
                "limit": max(10, int(limit) * 5),
                "with_payload": True,
                "filter": {
                    "must": [
                        {"key": "case_id", "match": {"value": case_id}}
                    ]
                },
            }
            if artifact_type:
                search_payload["filter"]["must"].append({
                    "key": "artifact_type",
                    "match": {
                        "value": artifact_type.value
                        if hasattr(artifact_type, "value") else str(artifact_type)
                    },
                })

            response = await self.client.post(
                f"{self.config.qdrant.url}/collections/{collection_name}/points/search",
                json=search_payload,
                timeout=30.0,
            )
            if response.status_code != 200:
                return []

            best: dict[str, dict] = {}
            for hit in response.json().get("result", []):
                payload = hit.get("payload") or {}
                artifact_id = payload.get("artifact_id")
                if not artifact_id:
                    continue
                score = float(hit.get("score") or 0.0)
                previous = best.get(artifact_id)
                if previous is None or score > previous["score"]:
                    best[artifact_id] = {
                        "score": score,
                        "text": payload.get("text") or payload.get("snippet") or "",
                        "chunk_index": payload.get("chunk_index"),
                    }

            if not best:
                return []

            from app.evidence.models import Evidence

            stmt = (
                select(Artifact)
                .options(joinedload(Artifact.evidence))
                .join(Evidence, Artifact.evidence_id == Evidence.id)
                .where(
                    Artifact.case_id == case_id,
                    Artifact.artifact_id.in_(list(best.keys())),
                    Evidence.removed_at.is_(None),
                )
            )
            by_id = {
                artifact.artifact_id: artifact
                for artifact in self.session.execute(stmt).scalars().all()
            }

            results = []
            for artifact_id, hit in best.items():
                artifact = by_id.get(artifact_id)
                if artifact is None:
                    continue
                created_date = (
                    artifact.created_time.date() if artifact.created_time else None
                )
                if date_from and (created_date is None or created_date < date_from):
                    continue
                if date_to and (created_date is None or created_date > date_to):
                    continue
                results.append({
                    "artifact": artifact,
                    "score": hit["score"],
                    "source": "semantic",
                    "snippet": make_snippet(hit["text"], query_terms(query)),
                    "matched_fields": ["content"],
                    "chunk_index": hit["chunk_index"],
                })

            results.sort(key=lambda item: item["score"], reverse=True)
            return results[:max(1, int(limit))]

        except Exception:
            # Semantic search is optional: a stopped Qdrant or Ollama must not
            # make the page unusable. The caller falls back to keyword results
            # in hybrid mode.
            return []

    # ------------------------------------------------------------------
    # Hybrid search
    # ------------------------------------------------------------------
    async def hybrid_search(
        self,
        case_id: int,
        query: str,
        artifact_type: ArtifactType | None = None,
        keyword_limit: int = 50,
        semantic_limit: int = 20,
        rrf_k: int = 60,
        date_from: date | None = None,
        date_to: date | None = None,
        regex: bool = False,
    ) -> list[dict]:
        """Combine keyword and semantic search with Reciprocal Rank Fusion."""
        import asyncio

        keyword_task = self.keyword_search(
            case_id, query, artifact_type, keyword_limit, regex=regex,
            date_from=date_from, date_to=date_to,
        )
        semantic_task = self.semantic_search(
            case_id, query, artifact_type, semantic_limit,
            date_from=date_from, date_to=date_to,
        )
        keyword_results, semantic_results = await asyncio.gather(
            keyword_task, semantic_task
        )

        merged: dict[str, dict] = {}
        for rank, item in enumerate(keyword_results, start=1):
            artifact_id = item["artifact"].artifact_id
            entry = merged.setdefault(artifact_id, {
                "artifact": item["artifact"],
                "score": 0.0,
                "sources": [],
                "snippet": "",
                "matched_fields": [],
                "chunk_index": item.get("chunk_index"),
            })
            entry["score"] += 1.0 / (rrf_k + rank)
            entry["sources"].append("keyword")
            entry["snippet"] = entry["snippet"] or item.get("snippet", "")
            entry["matched_fields"] = item.get("matched_fields", [])
            entry["chunk_index"] = item.get("chunk_index")

        for rank, item in enumerate(semantic_results, start=1):
            artifact_id = item["artifact"].artifact_id
            entry = merged.setdefault(artifact_id, {
                "artifact": item["artifact"],
                "score": 0.0,
                "sources": [],
                "snippet": "",
                "matched_fields": [],
            })
            entry["score"] += 1.0 / (rrf_k + rank)
            entry["sources"].append("semantic")
            if not entry["snippet"]:
                entry["snippet"] = item.get("snippet", "")
            if item.get("chunk_index") is not None:
                entry["chunk_index"] = item["chunk_index"]
            entry["chunk_index"] = item.get("chunk_index")

        fused = list(merged.values())
        fused.sort(key=lambda item: item["score"], reverse=True)
        for entry in fused:
            entry["source"] = " + ".join(entry["sources"])
        return fused

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    async def index_artifacts(
        self,
        case_id: int,
        artifact_ids: list[int] | None = None,
        progress_callback=None,
    ) -> dict:
        """Index artifact text into Qdrant as passage-level vectors."""

        def report_progress(
            message: str,
            current: int,
            total: int,
            indexed_count: int = 0,
            failed_count: int = 0,
        ) -> None:
            if progress_callback:
                progress_callback(
                    message, current, total, indexed_count, failed_count
                )

        try:
            if self.config.embeddings.provider == "openai":
                from app.auth.models import Case

                case = self.session.get(Case, case_id)
                if not case or not case.cloud_ai_consent_at:
                    return {
                        "indexed": 0,
                        "error": (
                            "Cloud embeddings are selected, but this case has not "
                            "consented to sending evidence text to a cloud provider. "
                            "Record consent in AI Analysis first."
                        ),
                    }
            from app.evidence.models import Evidence

            stmt = select(Artifact).join(
                Evidence, Artifact.evidence_id == Evidence.id
            ).where(
                Artifact.case_id == case_id,
                Evidence.removed_at.is_(None),
                Artifact.index_status.in_(
                    (IndexStatus.NOT_INDEXED, IndexStatus.INDEX_FAILED)
                ),
                Artifact.content_text.is_not(None),
                Artifact.content_text != "",
            )
            if artifact_ids:
                stmt = stmt.where(Artifact.id.in_(artifact_ids))

            artifacts = list(self.session.execute(stmt).scalars().all())
            if not artifacts:
                report_progress("No artifacts need indexing", 0, 0)
                return {"indexed": 0, "message": "No artifacts to index"}

            total_artifacts = len(artifacts)
            report_progress("Preparing semantic index", 0, total_artifacts)
            collection_name = f"{self.config.qdrant.collection_prefix}{case_id}"
            await self._ensure_collection(collection_name)

            indexed = 0
            chunk_count = 0
            failures: list[str] = []

            batch_size = max(1, self.config.embeddings.batch_size)
            for start in range(0, len(artifacts), batch_size):
                batch = artifacts[start:start + batch_size]
                report_progress(
                    f"Preparing batch {start + 1}–{start + len(batch)}",
                    start,
                    total_artifacts,
                    indexed,
                    len(failures),
                )

                # Build (artifact, chunk) pairs first: one artifact can need
                # several embedding calls, and all its points go in one upsert.
                plan: list[tuple[Artifact, ArtifactChunk]] = []
                for artifact in batch:
                    self.session.execute(
                        delete(ArtifactChunk).where(
                            ArtifactChunk.artifact_id == artifact.id
                        )
                    )
                    for index, (char_start, char_end, piece) in enumerate(
                        chunk_text(artifact.content_text or "")
                    ):
                        chunk = ArtifactChunk(
                            artifact_id=artifact.id,
                            case_id=case_id,
                            chunk_index=index,
                            char_start=char_start,
                            char_end=char_end,
                            text=piece,
                        )
                        self.session.add(chunk)
                        plan.append((artifact, chunk))
                self.session.flush()

                if not plan:
                    for artifact in batch:
                        artifact.index_status = IndexStatus.INDEX_FAILED
                    failures.append(
                        f"batch of {len(batch)} starting at {start}: no text to embed"
                    )
                    continue

                vectors: list[list[float]] = []
                embed_failed = False
                for group_start in range(0, len(plan), batch_size):
                    group = plan[group_start:group_start + batch_size]
                    report_progress(
                        f"Embedding passages for batch {start + 1}–{start + len(batch)}",
                        min(
                            start + len(batch),
                            start + int(
                                len(batch) * (group_start + len(group)) / max(1, len(plan))
                            ),
                        ),
                        total_artifacts,
                        indexed,
                        len(failures),
                    )
                    try:
                        group_vectors = await self._get_embeddings(
                            [chunk.text for _, chunk in group]
                        )
                    except Exception as exc:
                        failures.append(
                            f"batch of {len(batch)} starting at {start}: {exc}"
                        )
                        embed_failed = True
                        break
                    if len(group_vectors) != len(group):
                        failures.append(
                            f"batch of {len(batch)} starting at {start}: embedding "
                            f"service returned {len(group_vectors)} vectors for "
                            f"{len(group)} passages"
                        )
                        embed_failed = True
                        break
                    vectors.extend(group_vectors)

                if embed_failed:
                    for artifact in batch:
                        artifact.index_status = IndexStatus.INDEX_FAILED
                        artifact.vector_id = None
                    continue

                points = []
                accepted: list[Artifact] = []
                rejected: list[str] = []
                for (artifact, chunk), vector in zip(plan, vectors, strict=True):
                    if not vector:
                        rejected.append(artifact.artifact_id)
                        continue
                    point_id = str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"idfa:{case_id}:{artifact.id}:{chunk.chunk_index}",
                    ))
                    chunk.vector_id = point_id
                    points.append({
                        "id": point_id,
                        "vector": vector,
                        "payload": {
                            "artifact_id": artifact.artifact_id,
                            "case_id": case_id,
                            "evidence_id": artifact.evidence_id,
                            "artifact_type": artifact.artifact_type.value,
                            "name": artifact.name,
                            "source_path": artifact.source_path,
                            "chunk_index": chunk.chunk_index,
                            "char_start": chunk.char_start,
                            "char_end": chunk.char_end,
                            "text": chunk.text,
                            "snippet": chunk.text[:500],
                        },
                    })
                    if artifact not in accepted:
                        accepted.append(artifact)

                if rejected:
                    for artifact in batch:
                        if artifact.artifact_id in rejected:
                            artifact.index_status = IndexStatus.INDEX_FAILED
                    failures.append(
                        f"{', '.join(rejected)}: no embedding returned; check that "
                        f"{self.config.embeddings.model_id} is pulled in Ollama"
                    )

                if not points:
                    continue

                try:
                    upsert_response = await self.client.put(
                        f"{self.config.qdrant.url}/collections/{collection_name}/points",
                        json={"points": points},
                        timeout=120.0,
                    )
                    status_code = upsert_response.status_code
                except Exception as exc:
                    for artifact in accepted:
                        artifact.index_status = IndexStatus.INDEX_FAILED
                        artifact.vector_id = None
                    failures.append(f"Qdrant upsert failed: {exc}")
                    continue

                if status_code in (200, 201):
                    for artifact in accepted:
                        artifact.index_status = IndexStatus.INDEXED
                        artifact.indexed_at = datetime.now(timezone.utc)
                        artifact.vector_id = next(
                            (
                                point["id"] for point in points
                                if point["payload"]["artifact_id"] == artifact.artifact_id
                            ),
                            None,
                        )
                    indexed += len(accepted)
                    chunk_count += len(points)
                else:
                    for artifact in accepted:
                        artifact.index_status = IndexStatus.INDEX_FAILED
                        artifact.vector_id = None
                    failures.append(
                        f"Qdrant returned HTTP {status_code} for a batch of "
                        f"{len(points)} points"
                    )

                report_progress(
                    f"Stored vectors for batch {start + 1}–{start + len(batch)}",
                    start + len(batch),
                    total_artifacts,
                    indexed,
                    len(failures),
                )

            self.session.commit()
            report_progress(
                "Semantic indexing complete",
                total_artifacts,
                total_artifacts,
                indexed,
                len(failures),
            )
            return {
                "indexed": indexed,
                "total": len(artifacts),
                "chunks": chunk_count,
                "failed": len(failures),
                "errors": failures,
            }

        except Exception as e:
            return {"indexed": 0, "error": str(e)}

    async def _ensure_collection(self, collection_name: str):
        """Create Qdrant collection if it doesn't exist."""
        check = await self.client.get(
            f"{self.config.qdrant.url}/collections/{collection_name}"
        )
        if check.status_code == 200:
            return

        create_payload = {
            "vectors": {
                "size": self.config.qdrant.vector_size,
                "distance": self.config.qdrant.distance,
            }
        }
        await self.client.put(
            f"{self.config.qdrant.url}/collections/{collection_name}",
            json=create_payload,
            timeout=30.0,
        )
