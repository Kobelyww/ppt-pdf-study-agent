from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any, Sequence

from src.db.models import Document, DocumentArtifactRecord, DocumentChunkRecord
from src.services.study_agent_documents import (
    StudyAgentDocumentError,
    StudyDocumentChunker,
    StudyDocumentEvidence,
)


@dataclass(frozen=True)
class DocumentIndexStatus:
    document_id: str
    status: str
    artifact_id: str | None
    chunk_count: int
    indexed_at: datetime | None
    fallback_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "status": self.status,
            "artifact_id": self.artifact_id,
            "chunk_count": self.chunk_count,
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
            "fallback_reason": self.fallback_reason,
        }


class StudyDocumentIndexService:
    def __init__(
        self,
        session_factory,
        *,
        chunker: StudyDocumentChunker | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.chunker = chunker or StudyDocumentChunker()

    def index_document(self, owner_id: str, document_id: str) -> DocumentIndexStatus:
        normalized_owner_id = _require_owner_id(owner_id)
        normalized_document_id = _require_document_id(document_id)
        with self.session_factory() as session:
            document = self._load_owned_document(
                session,
                owner_id=normalized_owner_id,
                document_id=normalized_document_id,
                require_ready=True,
            )
            artifact = self._latest_normalized_artifact(session, document_id=document.id)
            if artifact is None:
                raise _document_evidence_missing()
            artifact_id = artifact.id

        return self.index_artifact(
            owner_id=normalized_owner_id,
            document_id=normalized_document_id,
            artifact_id=artifact_id,
            require_ready=True,
        )

    def index_artifact(
        self,
        owner_id: str,
        document_id: str,
        artifact_id: str,
        require_ready: bool = True,
    ) -> DocumentIndexStatus:
        normalized_owner_id = _require_owner_id(owner_id)
        normalized_document_id = _require_document_id(document_id)
        normalized_artifact_id = str(artifact_id or "").strip()
        if not normalized_artifact_id:
            raise _document_evidence_missing()

        with self.session_factory() as session:
            with session.begin():
                document = self._load_owned_document(
                    session,
                    owner_id=normalized_owner_id,
                    document_id=normalized_document_id,
                    require_ready=require_ready,
                )
                artifact = (
                    session.query(DocumentArtifactRecord)
                    .filter(
                        DocumentArtifactRecord.id == normalized_artifact_id,
                        DocumentArtifactRecord.document_id == document.id,
                        DocumentArtifactRecord.artifact_type == "normalized_document",
                    )
                    .first()
                )
                if artifact is None or not artifact.content.strip():
                    raise _document_evidence_missing()

                chunks = self.chunker.chunk(
                    (
                        StudyDocumentEvidence(
                            document_id=document.id,
                            document_title=document.title,
                            owner_id=document.owner_id,
                            artifact_id=artifact.id,
                            artifact_type=artifact.artifact_type,
                            content=artifact.content,
                            artifact_metadata=dict(artifact.artifact_metadata or {}),
                            created_at=artifact.created_at,
                        ),
                    )
                )
                if not chunks:
                    raise _document_evidence_missing()

                indexed_at = datetime.now(timezone.utc)

                (
                    session.query(DocumentChunkRecord)
                    .filter(
                        DocumentChunkRecord.owner_id == normalized_owner_id,
                        DocumentChunkRecord.document_id == document.id,
                    )
                    .delete(synchronize_session=False)
                )

                for chunk in chunks:
                    metadata = dict(chunk["metadata"])
                    metadata["source_kind"] = "persisted_document_chunk"
                    chunk_index = int(metadata["chunk_index"])
                    content = str(chunk["content"])
                    session.add(
                        DocumentChunkRecord(
                            id=_chunk_id(
                                document_id=document.id,
                                artifact_id=artifact.id,
                                chunk_index=chunk_index,
                            ),
                            owner_id=document.owner_id,
                            document_id=document.id,
                            artifact_id=artifact.id,
                            chunk_index=chunk_index,
                            chunk_count=len(chunks),
                            source=str(chunk["source"]),
                            content=content,
                            chunk_metadata=metadata,
                            content_hash=_content_hash(
                                content=content,
                                source=str(chunk["source"]),
                                artifact_id=artifact.id,
                                chunk_index=chunk_index,
                            ),
                            created_at=indexed_at,
                            updated_at=indexed_at,
                        )
                    )

                status = DocumentIndexStatus(
                    document_id=document.id,
                    status="indexed",
                    artifact_id=artifact.id,
                    chunk_count=len(chunks),
                    indexed_at=indexed_at if chunks else None,
                    fallback_reason=None,
                )

        return status

    def status(self, owner_id: str, document_id: str) -> DocumentIndexStatus:
        normalized_owner_id = _require_owner_id(owner_id)
        normalized_document_id = _require_document_id(document_id)
        with self.session_factory() as session:
            document = self._load_owned_document(
                session,
                owner_id=normalized_owner_id,
                document_id=normalized_document_id,
                require_ready=True,
            )
            latest_artifact = self._latest_normalized_artifact(session, document_id=document.id)
            chunks = (
                session.query(DocumentChunkRecord)
                .filter(
                    DocumentChunkRecord.owner_id == normalized_owner_id,
                    DocumentChunkRecord.document_id == document.id,
                )
                .order_by(DocumentChunkRecord.chunk_index)
                .all()
            )

            if latest_artifact is None:
                return DocumentIndexStatus(
                    document_id=document.id,
                    status="missing",
                    artifact_id=None,
                    chunk_count=0,
                    indexed_at=None,
                    fallback_reason="normalized_artifact_missing",
                )

            if not chunks:
                return DocumentIndexStatus(
                    document_id=document.id,
                    status="fallback_available",
                    artifact_id=latest_artifact.id,
                    chunk_count=0,
                    indexed_at=None,
                    fallback_reason="persisted_chunks_missing",
                )

            indexed_artifact_id = str(chunks[0].artifact_id)
            indexed_at = max((chunk.updated_at or chunk.created_at) for chunk in chunks)
            if indexed_artifact_id != latest_artifact.id:
                return DocumentIndexStatus(
                    document_id=document.id,
                    status="stale",
                    artifact_id=indexed_artifact_id,
                    chunk_count=len(chunks),
                    indexed_at=indexed_at,
                    fallback_reason="latest_artifact_not_indexed",
                )

            return DocumentIndexStatus(
                document_id=document.id,
                status="indexed",
                artifact_id=indexed_artifact_id,
                chunk_count=len(chunks),
                indexed_at=indexed_at,
                fallback_reason=None,
            )

    def load_chunks(
        self,
        owner_id: str,
        document_ids: Sequence[str],
    ) -> tuple[dict[str, Any], ...]:
        normalized_owner_id = _require_owner_id(owner_id)
        requested_ids = _dedupe_nonempty(document_ids)
        if not requested_ids:
            return ()

        with self.session_factory() as session:
            rows = (
                session.query(DocumentChunkRecord)
                .filter(
                    DocumentChunkRecord.owner_id == normalized_owner_id,
                    DocumentChunkRecord.document_id.in_(requested_ids),
                )
                .order_by(DocumentChunkRecord.document_id, DocumentChunkRecord.chunk_index)
                .all()
            )
            return tuple(
                {
                    "content": row.content,
                    "source": row.source,
                    "metadata": dict(row.chunk_metadata or {}),
                }
                for row in rows
            )

    def _load_owned_document(
        self,
        session,
        *,
        owner_id: str,
        document_id: str,
        require_ready: bool,
    ) -> Document:
        document = (
            session.query(Document)
            .filter(Document.owner_id == owner_id, Document.id == document_id)
            .first()
        )
        if document is None:
            raise StudyAgentDocumentError(
                status_code=404,
                code="document_unavailable",
                detail="Selected document is unavailable to the current user.",
            )
        if require_ready and document.status != "ready":
            raise StudyAgentDocumentError(
                status_code=422,
                code="document_not_ready",
                detail=(
                    f"Document {document.id} must finish processing before "
                    "Study Agent can use it."
                ),
            )
        return document

    def _latest_normalized_artifact(self, session, *, document_id: str) -> DocumentArtifactRecord | None:
        artifacts = (
            session.query(DocumentArtifactRecord)
            .filter(
                DocumentArtifactRecord.document_id == document_id,
                DocumentArtifactRecord.artifact_type == "normalized_document",
            )
            .order_by(DocumentArtifactRecord.created_at.desc())
            .all()
        )
        for artifact in artifacts:
            if artifact.content.strip():
                return artifact
        return None


def _require_owner_id(owner_id: str) -> str:
    normalized_owner_id = str(owner_id or "").strip()
    if not normalized_owner_id:
        raise StudyAgentDocumentError(
            status_code=422,
            code="authentication_required",
            detail="Study Agent requires an authenticated user.",
        )
    return normalized_owner_id


def _require_document_id(document_id: str) -> str:
    normalized_document_id = str(document_id or "").strip()
    if not normalized_document_id:
        raise StudyAgentDocumentError(
            status_code=422,
            code="document_scope_required",
            detail="Study Agent requires explicit document selection.",
        )
    return normalized_document_id


def _document_evidence_missing() -> StudyAgentDocumentError:
    return StudyAgentDocumentError(
        status_code=422,
        code="document_evidence_missing",
        detail="Processed document evidence is unavailable.",
    )


def _dedupe_nonempty(values: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        normalized = str(value).strip()
        if normalized:
            seen.setdefault(normalized, None)
    return tuple(seen)


def _content_hash(*, content: str, source: str, artifact_id: str, chunk_index: int) -> str:
    payload = "\n".join(
        (
            f"source:{source}",
            f"artifact_id:{artifact_id}",
            f"chunk_index:{chunk_index}",
            f"content:{content}",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _chunk_id(*, document_id: str, artifact_id: str, chunk_index: int) -> str:
    digest = hashlib.sha256(f"{document_id}:{artifact_id}:{chunk_index}".encode("utf-8")).hexdigest()
    return f"chunk:{digest[:58]}"
