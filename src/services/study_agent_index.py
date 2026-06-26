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
            artifact_ids = {str(chunk.artifact_id) for chunk in chunks}
            if artifact_ids != {latest_artifact.id}:
                stale_artifact_id = next(
                    artifact_id
                    for artifact_id in artifact_ids
                    if artifact_id != latest_artifact.id
                )
                return DocumentIndexStatus(
                    document_id=document.id,
                    status="stale",
                    artifact_id=stale_artifact_id,
                    chunk_count=len(chunks),
                    indexed_at=indexed_at,
                    fallback_reason="latest_artifact_not_indexed",
                )

            if not persisted_chunk_set_is_complete(
                chunks,
                document_id=document.id,
                artifact_id=latest_artifact.id,
            ):
                return DocumentIndexStatus(
                    document_id=document.id,
                    status="fallback_available",
                    artifact_id=latest_artifact.id,
                    chunk_count=len(chunks),
                    indexed_at=indexed_at,
                    fallback_reason="persisted_chunks_incomplete",
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


def persisted_chunk_set_is_complete(
    chunks: Sequence[Any],
    *,
    document_id: str,
    artifact_id: str,
) -> bool:
    if not chunks:
        return False

    expected_document_id = str(document_id)
    expected_artifact_id = str(artifact_id)
    chunk_indexes: set[int] = set()
    chunk_count: int | None = None

    for chunk in chunks:
        row_document_id = _chunk_value(chunk, "document_id")
        row_artifact_id = _chunk_value(chunk, "artifact_id")
        metadata = _chunk_metadata(chunk)
        metadata_document_id = metadata.get("document_id")
        metadata_artifact_id = metadata.get("artifact_id")
        metadata_chunk_index = metadata.get("chunk_index")
        metadata_chunk_count = metadata.get("chunk_count")
        row_chunk_index = _chunk_value(chunk, "chunk_index", metadata_chunk_index)
        row_chunk_count = _chunk_value(chunk, "chunk_count", metadata_chunk_count)

        if str(row_document_id or "") != expected_document_id:
            return False
        if str(row_artifact_id or "") != expected_artifact_id:
            return False
        if str(metadata_document_id or "") != expected_document_id:
            return False
        if str(metadata_artifact_id or "") != expected_artifact_id:
            return False

        try:
            current_chunk_index = int(row_chunk_index)
            current_chunk_count = int(row_chunk_count)
            current_metadata_chunk_index = int(metadata_chunk_index)
            current_metadata_chunk_count = int(metadata_chunk_count)
        except (TypeError, ValueError):
            return False

        if current_chunk_count <= 0:
            return False
        if current_metadata_chunk_count != current_chunk_count:
            return False
        if current_metadata_chunk_index != current_chunk_index:
            return False
        if chunk_count is None:
            chunk_count = current_chunk_count
        elif chunk_count != current_chunk_count:
            return False
        chunk_indexes.add(current_chunk_index)

    if chunk_count is None or len(chunks) != chunk_count:
        return False
    return chunk_indexes == set(range(chunk_count))


def _chunk_metadata(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        metadata = chunk.get("metadata", {})
    else:
        metadata = getattr(chunk, "chunk_metadata", {})
    return dict(metadata or {})


def _chunk_value(chunk: Any, key: str, default: Any = None) -> Any:
    if isinstance(chunk, dict):
        metadata = chunk.get("metadata", {})
        return dict(metadata or {}).get(key, default)
    return getattr(chunk, key, default)


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
