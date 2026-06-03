"""Optional evidence boosters for Website Proof.

Text-first MVP for documents, profiles, and certificates.  It never scrapes
LinkedIn or invents metadata; every skill signal comes from submitted text.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any, Literal

SourceType = Literal["document", "linkedin_profile", "certificate_transcript"]

_TABLE = "optional_evidence_submissions"

_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
_MAX_EXTRACT_CHARS = 120_000  # ~30 k tokens — enough for analysis without memory blow-up


@dataclass
class DocumentChunk:
    """A piece of extracted text with optional provenance."""
    text: str
    page_number: int | None = None
    section_label: str | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass
class ExtractedDocument:
    file_name: str
    file_type: str  # pdf | docx | txt | md
    chunks: list[DocumentChunk] = field(default_factory=list)
    status: str = "ok"          # ok | no_text_found | unsupported_file | extraction_failed
    error_message: str | None = None

    @property
    def full_text(self) -> str:
        return "\n\n".join(c.text for c in self.chunks)

    @property
    def preview(self) -> str:
        return self.full_text[:600]


def extract_document_text(file_bytes: bytes, filename: str) -> ExtractedDocument:
    """Extract text + provenance from an uploaded document.

    Supported: PDF (page numbers), DOCX (paragraph index), TXT/MD (line ranges).
    Returns ExtractedDocument with status set accordingly — never raises.
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(file_bytes, filename)
    if lower.endswith(".docx"):
        return _extract_docx(file_bytes, filename)
    if lower.endswith(".txt") or lower.endswith(".md"):
        return _extract_text(file_bytes, filename)

    ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
    return ExtractedDocument(
        file_name=filename,
        file_type=ext.lstrip(".") or "unknown",
        status="unsupported_file",
        error_message=f"File type '{ext}' is not supported. Upload PDF, DOCX, TXT, or MD.",
    )


def _extract_pdf(file_bytes: bytes, filename: str) -> ExtractedDocument:
    try:
        import pypdf  # optional dep — checked at call time
    except ImportError:
        return ExtractedDocument(
            file_name=filename, file_type="pdf",
            status="extraction_failed",
            error_message="PDF extraction library (pypdf) is not installed on this server.",
        )
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        chunks: list[DocumentChunk] = []
        total_chars = 0
        for i, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            page_text = page_text.strip()
            if not page_text:
                continue
            chunks.append(DocumentChunk(text=page_text, page_number=i))
            total_chars += len(page_text)
            if total_chars >= _MAX_EXTRACT_CHARS:
                break
        if not chunks:
            return ExtractedDocument(
                file_name=filename, file_type="pdf",
                status="no_text_found",
                error_message="No selectable text found. OCR document extraction not yet available.",
            )
        return ExtractedDocument(file_name=filename, file_type="pdf", chunks=chunks)
    except Exception as exc:
        return ExtractedDocument(
            file_name=filename, file_type="pdf",
            status="extraction_failed",
            error_message=f"PDF extraction error: {exc}",
        )


def _extract_docx(file_bytes: bytes, filename: str) -> ExtractedDocument:
    try:
        import docx  # python-docx
    except ImportError:
        return ExtractedDocument(
            file_name=filename, file_type="docx",
            status="extraction_failed",
            error_message="DOCX extraction library (python-docx) is not installed on this server.",
        )
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        chunks: list[DocumentChunk] = []
        total_chars = 0
        for idx, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if not text:
                continue
            style = para.style.name if para.style else None
            chunks.append(DocumentChunk(text=text, section_label=style, page_number=None))
            total_chars += len(text)
            if total_chars >= _MAX_EXTRACT_CHARS:
                break
        if not chunks:
            return ExtractedDocument(
                file_name=filename, file_type="docx",
                status="no_text_found",
                error_message="No text paragraphs found in this DOCX file.",
            )
        return ExtractedDocument(file_name=filename, file_type="docx", chunks=chunks)
    except Exception as exc:
        return ExtractedDocument(
            file_name=filename, file_type="docx",
            status="extraction_failed",
            error_message=f"DOCX extraction error: {exc}",
        )


def _extract_text(file_bytes: bytes, filename: str) -> ExtractedDocument:
    file_type = "md" if filename.lower().endswith(".md") else "txt"
    try:
        raw = file_bytes.decode("utf-8", errors="replace")
        lines = raw.splitlines()
        chunks: list[DocumentChunk] = []
        total_chars = 0
        para_lines: list[str] = []
        para_start: int | None = None
        for i, line in enumerate(lines, start=1):
            if line.strip():
                if para_start is None:
                    para_start = i
                para_lines.append(line)
            else:
                if para_lines:
                    text = " ".join(para_lines).strip()
                    chunks.append(DocumentChunk(
                        text=text, line_start=para_start, line_end=i - 1,
                    ))
                    total_chars += len(text)
                    para_lines = []
                    para_start = None
                    if total_chars >= _MAX_EXTRACT_CHARS:
                        break
        if para_lines:
            text = " ".join(para_lines).strip()
            chunks.append(DocumentChunk(text=text, line_start=para_start, line_end=len(lines)))
        if not chunks:
            return ExtractedDocument(
                file_name=filename, file_type=file_type,
                status="no_text_found",
                error_message="No text content found in this file.",
            )
        return ExtractedDocument(file_name=filename, file_type=file_type, chunks=chunks)
    except Exception as exc:
        return ExtractedDocument(
            file_name=filename, file_type=file_type,
            status="extraction_failed",
            error_message=f"Text extraction error: {exc}",
        )

_SKILL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Machine Learning", ("machine learning", "model training", "supervised learning", "classification model", "cnn model")),
    ("Deep Learning", ("deep learning", "neural network", "cnn", "convolutional", "tensorflow", "pytorch")),
    ("TensorFlow", ("tensorflow", "tf.keras", "keras")),
    ("Computer Vision", ("computer vision", "image classification", "opencv", "cnn", "object detection")),
    ("Model Evaluation", ("accuracy", "f1-score", "f1 score", "roc-auc", "roc auc", "precision", "recall")),
    ("Backend API", ("rest api", "backend api", "api endpoint", "fastapi endpoint")),
    ("FastAPI", ("fastapi", "fast api")),
    ("PostgreSQL", ("postgresql", "postgres", "sql database")),
    ("API Development", ("api development", "rest api", "endpoint", "http api")),
    ("Docker", ("docker", "container", "dockerfile")),
    ("DevOps", ("deployment", "ci/cd", "pipeline", "kubernetes", "docker deployment")),
    ("Data Visualization", ("data visualization", "dashboard", "chart", "plotly", "d3.js", "d3 ")),
    ("JavaScript", ("javascript", "typescript", "d3.js", "react", "node.js")),
    ("Dashboard Development", ("dashboard", "analytics dashboard", "interactive dashboard")),
    ("Python", ("python", "pandas", "numpy", "scikit-learn", "sklearn")),
    ("Data Science", ("data science", "data scientist", "data analysis", "recommendation system")),
    ("Recommendation Systems", ("recommendation system", "recommender", "collaborative filtering")),
    ("Technical Documentation", ("technical documentation", "project report", "methodology", "limitations")),
]

_ISSUER_PATTERNS = (
    r"(?:issuer|issued by|institution|university|provider)[:\s]+([A-Z][A-Za-z0-9 &.,-]{2,80})",
    r"(Coursera|edX|Udacity|Stanford University|MIT|Google|Microsoft|AWS|Amazon Web Services|IBM)",
)
_TITLE_PATTERNS = (
    r"(?:certificate|course|program|transcript)[:\s]+([A-Z][A-Za-z0-9 &/.,:+-]{3,100})",
    r"(Machine Learning|Deep Learning|Data Science|Cloud Practitioner|Computer Vision|Full Stack|Backend API)",
)
_DATE_PATTERN = r"\b(?:20\d{2}|19\d{2})(?:[-/]\d{1,2})?(?:[-/]\d{1,2})?\b"


@dataclass
class OptionalEvidenceAnalysis:
    status: str
    source_type: SourceType
    summary: str
    evidence_objects: list[dict[str, Any]]
    analysis_json: dict[str, Any]


def _sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [c.strip() for c in chunks if len(c.strip()) >= 12]


def _page_chunks(text: str) -> list[tuple[int | None, str]]:
    # Accept explicit markers from callers/tests: "\f" or "--- page 2 ---".
    if "\f" in text:
        return [(i + 1, part.strip()) for i, part in enumerate(text.split("\f")) if part.strip()]
    marker = re.compile(r"---\s*page\s+(\d+)\s*---", re.I)
    matches = list(marker.finditer(text))
    if not matches:
        return [(None, text)]
    chunks: list[tuple[int | None, str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunks.append((int(match.group(1)), text[start:end].strip()))
    return [(p, c) for p, c in chunks if c]


def _confidence(snippet: str, source_type: SourceType) -> str:
    lower = snippet.lower()
    detail = sum(1 for kw in ("built", "implemented", "evaluated", "deployed", "accuracy", "f1", "api", "dashboard") if kw in lower)
    if source_type == "certificate_transcript":
        return "medium"
    if detail >= 2:
        return "high"
    if len(snippet.split()) >= 8:
        return "medium"
    return "low"


def _find_meta(text: str) -> dict[str, str | None]:
    def first(patterns: tuple[str, ...]) -> str | None:
        for pat in patterns:
            m = re.search(pat, text or "", re.I)
            if m:
                return m.group(1).strip(" .,-")
        return None

    date_match = re.search(_DATE_PATTERN, text or "")
    return {
        "issuer": first(_ISSUER_PATTERNS),
        "title": first(_TITLE_PATTERNS),
        "date": date_match.group(0) if date_match else None,
    }


def _analyze_chunks(
    chunks: list[tuple[int | None, str | None, str]],
    *,
    source_type: SourceType,
    profile_url: str | None,
    section_label: str | None,
    file_path: str | None,
    file_name: str | None,
    file_type: str | None,
    meta: dict[str, Any],
    line_refs: list[tuple[int | None, int | None]] | None = None,
) -> tuple[list[dict[str, Any]], str, str]:
    """Core extraction loop; chunks = [(page_num, section_label, text)]."""
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    evidence_type = {
        "document": "document_snippet",
        "linkedin_profile": "profile_snippet",
        "certificate_transcript": "certificate_or_transcript_snippet",
    }[source_type]

    for chunk_idx, (page_number, chunk_section, chunk_text) in enumerate(chunks):
        for sentence in _sentences(chunk_text):
            lower = sentence.lower()
            for skill, keywords in _SKILL_RULES:
                hits = [kw for kw in keywords if kw in lower]
                if not hits:
                    continue
                key = (skill, sentence[:120])
                if key in seen:
                    continue
                seen.add(key)
                conf = _confidence(sentence, source_type)
                lr = line_refs[chunk_idx] if line_refs and chunk_idx < len(line_refs) else (None, None)
                evidence.append({
                    "source_type": source_type,
                    "evidence_type": evidence_type,
                    "skill_name": skill,
                    "confidence": conf,
                    "snippet": sentence[:280],
                    "reason": f"Supported by {source_type.replace('_', ' ')} text mentioning {', '.join(hits[:3])}.",
                    "page_number": page_number,
                    "profile_url": profile_url,
                    "section_label": chunk_section or section_label,
                    "file_path": file_path,
                    "file_name": file_name,
                    "file_type": file_type,
                    "line_start": lr[0],
                    "line_end": lr[1],
                    "issuer": meta.get("issuer"),
                    "title": meta.get("title"),
                    "date": meta.get("date"),
                })
            if len(evidence) >= 20:
                break
        if len(evidence) >= 20:
            break

    status = "analyzed" if evidence else "needs_review"
    summary = (
        f"Extracted {len(evidence)} evidence item(s)."
        if evidence else "No concrete skill evidence found in submitted text."
    )
    return evidence, status, summary


def analyze_optional_evidence(
    *,
    source_type: SourceType,
    raw_text: str = "",
    profile_url: str | None = None,
    section_label: str | None = None,
    file_path: str | None = None,
    file_name: str | None = None,
    file_type: str | None = None,
) -> OptionalEvidenceAnalysis:
    text = (raw_text or "").strip()
    if not text and source_type == "linkedin_profile" and profile_url:
        return OptionalEvidenceAnalysis(
            status="url_added",
            source_type=source_type,
            summary="Profile URL added. Paste public profile text for skill analysis.",
            evidence_objects=[],
            analysis_json={"profile_url": profile_url, "needs_more_detail": True},
        )
    if len(text) < 20:
        return OptionalEvidenceAnalysis(
            status="needs_review",
            source_type=source_type,
            summary="Evidence text is too short to extract reliable skills.",
            evidence_objects=[],
            analysis_json={"profile_url": profile_url, "file_path": file_path},
        )

    meta = _find_meta(text) if source_type == "certificate_transcript" else {}
    raw_chunks = [(p, None, t) for p, t in _page_chunks(text)]
    evidence, status, summary = _analyze_chunks(
        raw_chunks, source_type=source_type, profile_url=profile_url,
        section_label=section_label, file_path=file_path,
        file_name=file_name, file_type=file_type, meta=meta,
    )
    return OptionalEvidenceAnalysis(
        status=status,
        source_type=source_type,
        summary=summary,
        evidence_objects=evidence,
        analysis_json={
            "source_type": source_type,
            "summary": summary,
            "detected_skills": sorted({e["skill_name"] for e in evidence}),
            "profile_url": profile_url,
            "section_label": section_label,
            "file_path": file_path,
            "file_name": file_name,
            "file_type": file_type,
            **meta,
        },
    )


def analyze_from_extracted_document(
    doc: ExtractedDocument,
    *,
    source_type: SourceType = "document",
    profile_url: str | None = None,
) -> OptionalEvidenceAnalysis:
    """Analyze an already-extracted document's chunks with full provenance."""
    if doc.status != "ok":
        return OptionalEvidenceAnalysis(
            status=doc.status,
            source_type=source_type,
            summary=doc.error_message or "Document extraction failed.",
            evidence_objects=[],
            analysis_json={
                "source_type": source_type,
                "file_name": doc.file_name,
                "file_type": doc.file_type,
                "extraction_status": doc.status,
                "error": doc.error_message,
            },
        )

    raw_chunks = [
        (c.page_number, c.section_label, c.text) for c in doc.chunks
    ]
    line_refs = [(c.line_start, c.line_end) for c in doc.chunks]
    meta = _find_meta(doc.full_text) if source_type == "certificate_transcript" else {}

    evidence, status, summary = _analyze_chunks(
        raw_chunks, source_type=source_type, profile_url=profile_url,
        section_label=None, file_path=None,
        file_name=doc.file_name, file_type=doc.file_type,
        meta=meta, line_refs=line_refs,
    )
    return OptionalEvidenceAnalysis(
        status=status,
        source_type=source_type,
        summary=summary,
        evidence_objects=evidence,
        analysis_json={
            "source_type": source_type,
            "summary": summary,
            "detected_skills": sorted({e["skill_name"] for e in evidence}),
            "file_name": doc.file_name,
            "file_type": doc.file_type,
            "extracted_text_preview": doc.preview,
            **meta,
        },
    )


class OptionalEvidenceService:
    def __init__(self, db: Any) -> None:
        self._db = db

    def submit_file(
        self,
        *,
        user_id: str,
        proof_session_id: str | None,
        file_bytes: bytes,
        filename: str,
    ) -> dict[str, Any]:
        doc = extract_document_text(file_bytes, filename)
        analysis = analyze_from_extracted_document(doc, source_type="document")
        payload: dict[str, Any] = {
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "source_type": "document",
            "status": analysis.status,
            "file_path": filename,
            "profile_url": None,
            "raw_text": None,
            "analysis_json": {
                **analysis.analysis_json,
                "file_name": doc.file_name,
                "file_type": doc.file_type,
                "extracted_text_preview": doc.preview,
            },
            "evidence_objects": analysis.evidence_objects,
        }
        try:
            resp = self._db.table(_TABLE).insert(payload).execute()
            rows = resp.data or []
            return rows[0] if rows else payload
        except Exception:
            return payload

    def submit_text(
        self,
        *,
        user_id: str,
        proof_session_id: str | None,
        source_type: SourceType,
        raw_text: str = "",
        profile_url: str | None = None,
        section_label: str | None = None,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        analysis = analyze_optional_evidence(
            source_type=source_type,
            raw_text=raw_text,
            profile_url=profile_url,
            section_label=section_label,
            file_path=file_path,
        )
        payload = {
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "source_type": source_type,
            "status": analysis.status,
            "profile_url": profile_url,
            "file_path": file_path,
            "raw_text": raw_text or None,
            "analysis_json": analysis.analysis_json,
            "evidence_objects": analysis.evidence_objects,
        }
        try:
            resp = self._db.table(_TABLE).insert(payload).execute()
            rows = resp.data or []
            return rows[0] if rows else payload
        except Exception:
            # Tests and local dev can still use the analyzed shape without DB.
            return payload

    def list_for_session(self, *, user_id: str, proof_session_id: str) -> list[dict[str, Any]]:
        try:
            resp = (
                self._db.table(_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", proof_session_id)
                .order("created_at", desc=True)
                .execute()
            )
            return resp.data or []
        except Exception:
            return []
