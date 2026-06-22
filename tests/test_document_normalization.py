from src.normalization.normalizer import DocumentNormalizer
from src.parsers.marker_pdf import Formula, Section, StructuredDocument


def test_normalizer_preserves_section_source_spans():
    source = StructuredDocument(
        title="Calculus Notes",
        sections=[
            Section(
                level=1,
                title="Derivatives",
                content="Derivative is rate of change.",
            )
        ],
        metadata={"source_path": "fixtures/calculus.pdf"},
    )

    normalized = DocumentNormalizer().normalize(source, document_id="doc-1")

    assert normalized.document_id == "doc-1"
    assert normalized.sections[0].title == "Derivatives"
    assert normalized.sections[0].source_spans[0].section_id == normalized.sections[0].id
    assert normalized.sections[0].source_spans[0].page_number is None
    assert normalized.sections[0].source_spans[0].missing_reason == "parser_did_not_provide_page"
    assert normalized.chunks[0].source_spans[0].section_id == normalized.sections[0].id


def test_normalizer_accepts_source_keyword_argument():
    source = StructuredDocument(
        title="Keyword Notes",
        sections=[Section(level=1, title="Vectors", content="A vector has magnitude.")],
    )

    normalized = DocumentNormalizer().normalize(source=source, document_id="doc-keyword")

    assert normalized.document_id == "doc-keyword"
    assert normalized.sections[0].title == "Vectors"


def test_normalizer_converts_formulas_to_assets():
    source = StructuredDocument(
        title="Formula Notes",
        sections=[Section(level=1, title="Chain Rule", content="Chain rule formula.")],
        formulas=[Formula(latex="(f \\circ g)'(x)=f'(g(x))g'(x)", page_number=2)],
    )

    normalized = DocumentNormalizer().normalize(source, document_id="doc-2")

    assert normalized.assets[0].asset_type == "formula"
    assert "f'(g(x))" in normalized.assets[0].description
    assert normalized.assets[0].source_span.page_number == 2


def test_normalizer_treats_default_formula_page_as_missing():
    source = StructuredDocument(
        title="Formula Notes",
        formulas=[Formula(latex="x^2")],
    )

    normalized = DocumentNormalizer().normalize(source=source, document_id="doc-page")

    assert normalized.assets[0].source_span.page_number is None
    assert normalized.assets[0].source_span.missing_reason == "parser_did_not_provide_page"


def test_normalizer_skips_blank_section_chunks():
    source = StructuredDocument(
        title="Blank Notes",
        sections=[Section(level=1, title="Empty", content="   ")],
    )

    normalized = DocumentNormalizer().normalize(source=source, document_id="doc-blank")

    assert normalized.sections[0].title == "Empty"
    assert normalized.chunks == []


def test_normalizer_anchors_document_level_formulas_to_document_section():
    source = StructuredDocument(
        title="Formula Notes",
        sections=[
            Section(level=1, title="Vectors", content="Vector content."),
            Section(level=1, title="Matrices", content="Matrix content."),
        ],
        formulas=[Formula(latex="A x = b", page_number=3)],
    )

    normalized = DocumentNormalizer().normalize(source=source, document_id="doc-formula")

    asset_span = normalized.assets[0].source_span
    section_ids = {section.id for section in normalized.sections}
    assert asset_span.section_id == "doc-formula:section:document"
    assert asset_span.section_id in section_ids
    assert asset_span.section_id != normalized.sections[0].id
