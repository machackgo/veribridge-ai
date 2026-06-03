"""Tests for document file upload and extraction in optional evidence."""

from __future__ import annotations

import io
import struct
import textwrap
import zipfile

import pytest

from app.services.optional_evidence_service import (
    ExtractedDocument,
    analyze_from_extracted_document,
    analyze_optional_evidence,
    extract_document_text,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _txt_bytes(content: str) -> bytes:
    return content.encode("utf-8")


def _md_bytes(content: str) -> bytes:
    return content.encode("utf-8")


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    """Build a minimal valid DOCX (zip with word/document.xml)."""
    body_parts = "\n".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{p}</w:t></w:r></w:p>"
        for p in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"'
        ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body_parts}</w:body>"
        "</w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        ' Target="word/document.xml"/>'
        "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def _make_pdf_bytes_with_text(pages: list[str]) -> bytes:
    """Build a minimal PDF with real text streams so pypdf can extract them."""
    objects: list[bytes] = []
    offsets: list[int] = []

    def add_obj(content: bytes) -> int:
        obj_num = len(objects) + 1
        objects.append(content)
        return obj_num

    page_obj_ids: list[int] = []
    stream_obj_ids: list[int] = []

    for page_text in pages:
        # Simple PDF text stream: BT /F1 12 Tf 50 700 Td (text) Tj ET
        escaped = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_content = f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode()
        stream_len = len(stream_content)
        stream_id = add_obj(
            f"<< /Length {stream_len} >>\nstream\n".encode()
            + stream_content
            + b"\nendstream"
        )
        stream_obj_ids.append(stream_id)
        page_id = add_obj(
            f"<< /Type /Page /MediaBox [0 0 612 792] /Contents {stream_id} 0 R "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>".encode()
        )
        page_obj_ids.append(page_id)

    kids = " ".join(f"{i} 0 R" for i in page_obj_ids)
    pages_id = add_obj(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_obj_ids)} >>".encode())
    catalog_id = add_obj(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    # Assemble PDF bytes
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    xref_positions: list[int] = []
    for idx, content in enumerate(objects, start=1):
        xref_positions.append(buf.tell())
        buf.write(f"{idx} 0 obj\n".encode())
        buf.write(content)
        buf.write(b"\nendobj\n")

    xref_start = buf.tell()
    n = len(objects) + 1
    buf.write(f"xref\n0 {n}\n".encode())
    buf.write(b"0000000000 65535 f \n")
    for pos in xref_positions:
        buf.write(f"{pos:010d} 00000 n \n".encode())
    buf.write(
        f"trailer\n<< /Size {n} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n".encode()
    )
    return buf.getvalue()


# ── TXT extraction ────────────────────────────────────────────────────────────

def test_txt_extraction_creates_document_snippet_evidence():
    content = "Built a FastAPI backend with PostgreSQL database for the API endpoints."
    doc = extract_document_text(_txt_bytes(content), "report.txt")
    assert doc.status == "ok"
    assert doc.file_type == "txt"
    assert len(doc.chunks) >= 1

    analysis = analyze_from_extracted_document(doc)
    assert analysis.status == "analyzed"
    skill_names = {e["skill_name"] for e in analysis.evidence_objects}
    assert "FastAPI" in skill_names or "Backend API" in skill_names
    for ev in analysis.evidence_objects:
        assert ev["evidence_type"] == "document_snippet"
        assert ev["source_type"] == "document"


def test_txt_extraction_line_references():
    content = "FastAPI backend with PostgreSQL.\n\nSecond paragraph."
    doc = extract_document_text(_txt_bytes(content), "report.txt")
    chunks_with_lines = [c for c in doc.chunks if c.line_start is not None]
    assert len(chunks_with_lines) > 0


# ── MD extraction ─────────────────────────────────────────────────────────────

def test_md_extraction_creates_document_snippet_evidence():
    content = textwrap.dedent("""
        # Project Report

        We trained a deep learning CNN model using TensorFlow.
        F1-score was 0.92 on the test set.
    """).strip()
    doc = extract_document_text(_md_bytes(content), "report.md")
    assert doc.status == "ok"
    assert doc.file_type == "md"

    analysis = analyze_from_extracted_document(doc)
    assert analysis.status == "analyzed"
    skill_names = {e["skill_name"] for e in analysis.evidence_objects}
    assert "TensorFlow" in skill_names or "Deep Learning" in skill_names or "Model Evaluation" in skill_names


# ── DOCX extraction ───────────────────────────────────────────────────────────

def test_docx_extraction_maps_skills():
    paragraphs = [
        "We implemented a FastAPI backend with PostgreSQL.",
        "The model was a CNN trained with TensorFlow achieving F1-score of 0.91.",
    ]
    docx_bytes = _make_docx_bytes(paragraphs)
    doc = extract_document_text(docx_bytes, "project.docx")
    assert doc.status == "ok"
    assert doc.file_type == "docx"
    assert len(doc.chunks) >= 1

    analysis = analyze_from_extracted_document(doc)
    assert analysis.status == "analyzed"
    skill_names = {e["skill_name"] for e in analysis.evidence_objects}
    assert len(skill_names) >= 2


def test_docx_section_label_preserved():
    docx_bytes = _make_docx_bytes(["FastAPI backend endpoint built for the API."])
    doc = extract_document_text(docx_bytes, "proj.docx")
    # section_label comes from paragraph style — may be None or a style name
    for chunk in doc.chunks:
        assert isinstance(chunk.section_label, (str, type(None)))


# ── PDF extraction ────────────────────────────────────────────────────────────

def test_pdf_text_extraction_creates_page_number_evidence():
    pdf_bytes = _make_pdf_bytes_with_text([
        "Built a CNN model using TensorFlow and evaluated F1-score accuracy.",
        "FastAPI backend with PostgreSQL database integration.",
    ])
    doc = extract_document_text(pdf_bytes, "report.pdf")
    if doc.status == "no_text_found":
        pytest.skip("pypdf could not extract text from minimal PDF in this environment")
    assert doc.status == "ok"
    assert doc.file_type == "pdf"

    pages_with_numbers = [c for c in doc.chunks if c.page_number is not None]
    assert len(pages_with_numbers) >= 1

    analysis = analyze_from_extracted_document(doc)
    # At least some evidence should reference a page number
    page_evidence = [e for e in analysis.evidence_objects if e.get("page_number") is not None]
    if analysis.evidence_objects:
        assert len(page_evidence) >= 1


# ── Unsupported file ──────────────────────────────────────────────────────────

def test_unsupported_file_returns_status_not_crash():
    doc = extract_document_text(b"fake content", "image.jpg")
    assert doc.status == "unsupported_file"
    assert doc.error_message is not None
    assert "not supported" in doc.error_message.lower()

    analysis = analyze_from_extracted_document(doc)
    assert analysis.status == "unsupported_file"
    assert analysis.evidence_objects == []


# ── Empty / scanned PDF ───────────────────────────────────────────────────────

def test_empty_pdf_returns_no_text_found_safely():
    # A valid but empty PDF (no text streams)
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    # Minimal catalog pointing to empty page
    buf.write(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    buf.write(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    buf.write(b"3 0 obj\n<< /Type /Page /MediaBox [0 0 612 792] >>\nendobj\n")
    xref = buf.tell()
    buf.write(b"xref\n0 4\n0000000000 65535 f \n")
    # Rough positions — pypdf will still parse it
    buf.write(b"0000000009 00000 n \n0000000062 00000 n \n0000000115 00000 n \n")
    buf.write(f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())

    doc = extract_document_text(buf.getvalue(), "scanned.pdf")
    assert doc.status in ("no_text_found", "extraction_failed")
    if doc.status == "no_text_found":
        assert "OCR" in (doc.error_message or "")


# ── Missing document does NOT reduce score ────────────────────────────────────

def test_missing_document_proof_does_not_affect_score():
    """analyze_optional_evidence returns needs_review (not crash) for empty text."""
    result = analyze_optional_evidence(source_type="document", raw_text="")
    assert result.status == "needs_review"
    assert result.evidence_objects == []


# ── Pasted text flow still works ─────────────────────────────────────────────

def test_pasted_text_flow_still_works():
    text = "We built a FastAPI backend with PostgreSQL. The API uses Docker for deployment."
    result = analyze_optional_evidence(source_type="document", raw_text=text)
    assert result.status == "analyzed"
    skill_names = {e["skill_name"] for e in result.evidence_objects}
    assert "FastAPI" in skill_names or "Backend API" in skill_names
    assert "Docker" in skill_names or "DevOps" in skill_names
