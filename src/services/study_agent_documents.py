from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from src.db.models import Document, DocumentArtifactRecord


@dataclass(frozen=True)
class StudyDocumentEvidence:
    document_id: str
    document_title: str
    owner_id: str
    artifact_id: str
    artifact_type: str
    content: str
    artifact_metadata: dict[str, Any]
    created_at: datetime


class StudyAgentDocumentError(ValueError):
    def __init__(self, *, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class StudyDocumentEvidenceSource:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def load(
        self,
        *,
        owner_id: str,
        document_ids: Sequence[str],
    ) -> tuple[StudyDocumentEvidence, ...]:
        normalized_owner_id = str(owner_id or "").strip()
        if not normalized_owner_id:
            raise StudyAgentDocumentError(
                status_code=422,
                code="authentication_required",
                detail="Study Agent requires an authenticated user.",
            )

        requested_ids = _dedupe_nonempty(document_ids)
        if not requested_ids:
            raise StudyAgentDocumentError(
                status_code=422,
                code="document_scope_required",
                detail="Study Agent requires explicit document selection.",
            )

        with self.session_factory() as session:
            documents = (
                session.query(Document)
                .filter(
                    Document.owner_id == normalized_owner_id,
                    Document.id.in_(requested_ids),
                )
                .all()
            )
            documents_by_id = {document.id: document for document in documents}
            if any(document_id not in documents_by_id for document_id in requested_ids):
                raise StudyAgentDocumentError(
                    status_code=404,
                    code="document_unavailable",
                    detail="Selected document is unavailable to the current user.",
                )

            evidence: list[StudyDocumentEvidence] = []
            for document_id in requested_ids:
                document = documents_by_id[document_id]
                if document.status != "ready":
                    raise StudyAgentDocumentError(
                        status_code=422,
                        code="document_not_ready",
                        detail=(
                            f"Document {document.id} must finish processing before "
                            "Study Agent can use it."
                        ),
                    )

                artifact = (
                    session.query(DocumentArtifactRecord)
                    .filter(
                        DocumentArtifactRecord.document_id == document.id,
                        DocumentArtifactRecord.artifact_type == "normalized_document",
                    )
                    .order_by(DocumentArtifactRecord.created_at.desc())
                    .first()
                )
                if artifact is None or not artifact.content.strip():
                    raise StudyAgentDocumentError(
                        status_code=422,
                        code="document_evidence_missing",
                        detail="Processed document evidence is unavailable.",
                    )

                evidence.append(
                    StudyDocumentEvidence(
                        document_id=document.id,
                        document_title=document.title,
                        owner_id=document.owner_id,
                        artifact_id=artifact.id,
                        artifact_type=artifact.artifact_type,
                        content=artifact.content,
                        artifact_metadata=dict(artifact.artifact_metadata or {}),
                        created_at=artifact.created_at,
                    )
                )

        return tuple(evidence)


def _dedupe_nonempty(values: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        normalized = str(value).strip()
        if normalized:
            seen.setdefault(normalized, None)
    return tuple(seen)
