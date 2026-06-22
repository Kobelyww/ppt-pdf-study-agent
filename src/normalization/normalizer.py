from __future__ import annotations

from src.normalization.document import (
    DocumentAsset,
    DocumentChunk,
    NormalizedDocument,
    NormalizedSection,
    SourceSpan,
)
from src.parsers.marker_pdf import StructuredDocument


class DocumentNormalizer:
    def normalize(self, source: StructuredDocument, document_id: str) -> NormalizedDocument:
        sections: list[NormalizedSection] = []
        chunks: list[DocumentChunk] = []

        for index, section in enumerate(source.sections):
            section_id = f"{document_id}:section:{index}"
            page_number = self._section_page_number(section)
            span = SourceSpan(
                section_id=section_id,
                page_number=page_number,
                missing_reason=None if page_number else "parser_did_not_provide_page",
                confidence=1.0 if page_number else 0.5,
            )
            normalized_section = NormalizedSection(
                id=section_id,
                parent_id=None,
                title=section.title,
                content=section.content,
                level=section.level,
                order_index=index,
                source_spans=[span],
            )
            sections.append(normalized_section)

            chunk_content = section.content.strip()
            if chunk_content:
                chunks.append(
                    DocumentChunk(
                        id=f"{section_id}:chunk:0",
                        section_id=section_id,
                        content=chunk_content,
                        chunk_index=0,
                        source_spans=[span],
                    )
                )

        asset_section_id = self._ensure_document_asset_section(
            sections=sections,
            document_id=document_id,
            title=source.title,
            needs_anchor=bool(source.formulas),
        )
        assets: list[DocumentAsset] = []
        for index, formula in enumerate(source.formulas):
            page_number = self._page_number_or_none(formula.page_number)
            assets.append(
                DocumentAsset(
                    id=f"{document_id}:formula:{index}",
                    asset_type="formula",
                    description=formula.latex,
                    source_span=SourceSpan(
                        section_id=asset_section_id,
                        page_number=page_number,
                        missing_reason=None if page_number else "parser_did_not_provide_page",
                        confidence=1.0 if page_number else 0.5,
                    ),
                    metadata={"latex": formula.latex},
                )
            )

        return NormalizedDocument(
            document_id=document_id,
            title=source.title,
            sections=sections,
            chunks=chunks,
            assets=assets,
            metadata=dict(source.metadata),
        )

    @staticmethod
    def _section_page_number(section) -> int | None:
        metadata = getattr(section, "metadata", {}) or {}
        page_number = metadata.get("page_number")
        return DocumentNormalizer._page_number_or_none(page_number)

    @staticmethod
    def _page_number_or_none(page_number: int | None) -> int | None:
        return page_number or None

    @staticmethod
    def _ensure_document_asset_section(
        *,
        sections: list[NormalizedSection],
        document_id: str,
        title: str,
        needs_anchor: bool,
    ) -> str:
        if not needs_anchor:
            return document_id

        section_id = f"{document_id}:section:document"
        sections.append(
            NormalizedSection(
                id=section_id,
                parent_id=None,
                title=title or "Document",
                content="",
                level=0,
                order_index=len(sections),
                source_spans=[
                    SourceSpan(
                        section_id=section_id,
                        confidence=0.5,
                        missing_reason="document_level_asset",
                    )
                ],
            )
        )
        return section_id
