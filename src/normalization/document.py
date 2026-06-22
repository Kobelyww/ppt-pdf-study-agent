from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceSpan:
    section_id: str
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    char_start: int | None = None
    char_end: int | None = None
    confidence: float = 1.0
    missing_reason: str | None = None


@dataclass(frozen=True)
class NormalizedSection:
    id: str
    parent_id: str | None
    title: str
    content: str
    level: int
    order_index: int
    source_spans: list[SourceSpan]


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    section_id: str
    content: str
    chunk_index: int
    source_spans: list[SourceSpan]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentAsset:
    id: str
    asset_type: str
    description: str
    source_span: SourceSpan
    storage_uri: str | None = None
    caption: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedDocument:
    document_id: str
    title: str
    sections: list[NormalizedSection]
    chunks: list[DocumentChunk]
    assets: list[DocumentAsset]
    metadata: dict[str, Any] = field(default_factory=dict)
