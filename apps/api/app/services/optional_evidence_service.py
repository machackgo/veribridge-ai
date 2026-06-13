"""Optional evidence boosters for Website Proof.

Text-first MVP for documents, profiles, and certificates.  It never scrapes
LinkedIn or invents metadata; every skill signal comes from submitted text.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

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

@dataclass(frozen=True)
class SkillRule:
    skill: str
    phrases: tuple[str, ...]
    context_terms: tuple[str, ...] = ()
    tool_terms: tuple[str, ...] = ()
    task_terms: tuple[str, ...] = ()
    result_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()


_GENERAL_TASK_TERMS = (
    "built", "implemented", "trained", "fine-tuned", "evaluated", "optimized",
    "deployed", "processed", "generated", "classified", "detected", "render",
    "renders", "rendered", "queried", "stored", "validated", "monitored",
)
_PROJECT_CONTEXT_TERMS = (
    "project", "application", "app", "system", "pipeline", "workflow", "model",
    "api", "dashboard", "frontend", "backend", "browser", "dataset", "results",
    "accuracy", "latency", "scene", "mesh", "geometry", "report",
)


_SKILL_RULES: tuple[SkillRule, ...] = (
    # 3D graphics / browser rendering
    SkillRule("Three.js", ("three.js", "three js", "threejs"), tool_terms=("three.js", "three js", "threejs"), task_terms=("render", "renders", "rendered", "implemented", "built"), result_terms=("interactive", "3d", "webgl", "scene", "object")),
    SkillRule("WebGL", ("webgl", "web gl"), tool_terms=("webgl", "web gl"), task_terms=("render", "renders", "rendered", "implemented"), result_terms=("browser", "3d", "graphics", "scene")),
    SkillRule("Interactive 3D Graphics", ("3d graphics", "interactive 3d", "3d rendering", "3d scene", "3d object"), context_terms=("render", "graphics", "scene", "object", "webgl", "three.js", "browser")),
    SkillRule("Computer Graphics", ("3d graphics", "interactive 3d", "3d rendering", "computer graphics", "geometry processing", "mesh processing", "scene", "camera", "controls", "material", "geometry"), context_terms=("3d", "webgl", "three.js", "rendering", "graphics", "mesh", "geometry", "browser")),
    SkillRule("Geometry Optimization", ("geometry optimization", "geometry processing", "mesh processing", "mesh simplification", "geometry simplifier"), task_terms=("optimized", "optimization", "simplification", "processing", "simplifier"), result_terms=("geometry", "mesh", "performance")),
    SkillRule("3D Mesh Simplification", ("mesh simplification", "simplifier", "geometry simplifier", "mesh processing"), context_terms=("mesh", "geometry", "3d", "graphics")),
    SkillRule("Frontend Development", ("browser rendering", "rendering pipeline", "javascript modules", "browser interaction", "frontend application", "frontend development", "react", "next.js", "nextjs", "typescript", "javascript"), context_terms=("frontend", "browser", "ui", "client", "react", "next", "javascript", "typescript", "3d", "webgl")),
    SkillRule("Browser Rendering", ("browser rendering", "rendering pipeline", "webgl rendering", "browser interaction"), context_terms=("browser", "webgl", "frontend", "rendering")),
    # AI / ML / data science
    SkillRule("Machine Learning", ("machine learning", "model training", "supervised learning", "classification model", "regression model", "cnn model"), task_terms=("trained", "evaluated", "classified", "predicted"), result_terms=("accuracy", "f1", "precision", "recall", "dataset")),
    SkillRule("Deep Learning", ("deep learning", "neural network", "cnn", "convolutional", "transformer", "pytorch", "tensorflow"), context_terms=("model", "training", "classification", "vision", "nlp", "dataset")),
    SkillRule("TensorFlow", ("tensorflow", "tf.keras", "keras"), tool_terms=("tensorflow", "tf.keras", "keras"), task_terms=("trained", "evaluated", "implemented"), result_terms=("model", "accuracy", "f1", "dataset")),
    SkillRule("NLP", ("nlp", "natural language processing", "text classification", "named entity recognition", "sentiment analysis", "llm assistant"), context_terms=("text", "language", "tokens", "embedding", "llm", "rag", "retrieval", "documents")),
    SkillRule("LLM", ("llm", "large language model", "gpt", "claude", "llama", "prompt engineering"), context_terms=("prompt", "generation", "rag", "retrieval", "embedding", "model")),
    SkillRule("RAG", ("rag", "retrieval augmented generation", "retrieval-augmented generation"), context_terms=("retrieval", "embedding", "vector", "documents", "llm")),
    SkillRule("Embeddings", ("embedding", "embeddings", "vector search", "semantic search", "vector database"), context_terms=("vector", "semantic", "retrieval", "rag", "documents")),
    SkillRule("Computer Vision", ("computer vision", "image recognition", "image classification", "opencv", "cnn for images", "object detection", "segmentation", "detection model", "webcam", "image processing", "visual perception", "pose detection", "ocr"), context_terms=("image", "video", "vision", "detection", "classification", "ocr", "webcam", "segmentation", "pose"), exclude_terms=("data visualization", "visualization", "visual analytics", "visual output", "svg", "chart", "charts", "graph gallery")),
    SkillRule("Object Detection", ("object detection", "yolo", "bounding box", "bounding boxes"), context_terms=("image", "vision", "detected", "model")),
    SkillRule("OCR", ("ocr", "text extraction", "optical character recognition"), context_terms=("image", "document", "text", "extraction")),
    SkillRule("Model Evaluation", ("accuracy", "f1-score", "f1 score", "roc-auc", "roc auc", "precision", "recall", "confusion matrix"), context_terms=("model", "evaluation", "evaluated", "test set", "validation")),
    SkillRule("MLOps", ("mlops", "model monitoring", "model registry", "model deployment", "experiment tracking", "drift monitoring"), context_terms=("model", "monitoring", "deployment", "tracking", "pipeline")),
    SkillRule("Data Science", ("data science", "data scientist", "data analysis", "recommendation system", "feature engineering"), context_terms=("dataset", "analysis", "model", "pandas", "visualization", "recommendation")),
    SkillRule("Data Analysis", ("data analysis", "exploratory analysis", "eda", "pandas", "numpy"), context_terms=("dataset", "analysis", "cleaning", "features")),
    SkillRule("Data Visualization", ("data visualization", "visual analytics", "visual output", "dashboard", "chart", "charts", "plotly", "d3.js", "d3 ", "matplotlib", "seaborn", "svg visualization"), context_terms=("dashboard", "chart", "charts", "visualization", "results", "analytics", "svg", "graph")),
    SkillRule("D3.js", ("d3.js", "d3 ", "d3 graph", "d3 chart"), tool_terms=("d3.js", "d3 "), task_terms=("built", "implemented", "rendered", "visualized"), result_terms=("chart", "charts", "svg", "graph", "visualization", "interactive")),
    SkillRule("Interactive Charts", ("interactive chart", "interactive charts", "chart interaction", "chart interactions", "interactive visualization", "hover tooltip", "tooltip", "brush", "zoom"), context_terms=("chart", "charts", "visualization", "svg", "d3", "interaction", "tooltip")),
    SkillRule("SVG Visualization", ("svg visualization", "svg chart", "svg charts", "svg", "scalable vector graphics"), context_terms=("visualization", "chart", "charts", "graph", "d3", "frontend")),
    SkillRule("Graph Analysis", ("graph analysis", "graph analytics", "graph gallery", "network graph", "graph visualization", "node-link", "nodes and edges", "nodes", "edges"), context_terms=("graph", "chart", "visualization", "network", "nodes", "edges", "analytics")),
    SkillRule("Python", ("python", "pandas", "numpy", "scikit-learn", "sklearn"), tool_terms=("python", "pandas", "numpy", "scikit-learn", "sklearn"), task_terms=("implemented", "trained", "analyzed", "processed")),
    # Backend / frontend / databases
    SkillRule("Backend API", ("rest api", "backend api", "api endpoint", "fastapi endpoint", "server endpoint"), context_terms=("api", "endpoint", "backend", "server", "request", "response")),
    SkillRule("API Development", ("api development", "rest api", "endpoint", "http api", "openapi", "swagger"), context_terms=("api", "endpoint", "http", "request", "response")),
    SkillRule("FastAPI", ("fastapi", "fast api"), tool_terms=("fastapi", "fast api"), task_terms=("implemented", "built", "served", "validated"), result_terms=("api", "endpoint", "backend")),
    SkillRule("Flask", ("flask", "flask api"), tool_terms=("flask",), task_terms=("implemented", "built", "served"), result_terms=("api", "backend", "endpoint")),
    SkillRule("Django", ("django", "django rest framework", "drf"), tool_terms=("django", "django rest framework", "drf"), task_terms=("implemented", "built", "served"), result_terms=("api", "backend", "endpoint")),
    SkillRule("React", ("react", "react.js", "reactjs"), tool_terms=("react", "react.js", "reactjs"), task_terms=("built", "implemented", "rendered"), result_terms=("ui", "component", "frontend", "application")),
    SkillRule("Next.js", ("next.js", "nextjs", "next js"), tool_terms=("next.js", "nextjs", "next js"), task_terms=("built", "implemented", "rendered"), result_terms=("frontend", "application", "route", "server")),
    SkillRule("JavaScript", ("javascript", "javascript modules", "node.js", "d3.js", "d3 "), tool_terms=("javascript", "node.js", "d3.js"), task_terms=("implemented", "built", "rendered"), result_terms=("frontend", "browser", "module", "application")),
    SkillRule("TypeScript", ("typescript", "tsx", "ts-node"), tool_terms=("typescript", "tsx"), task_terms=("implemented", "typed", "built"), result_terms=("frontend", "api", "application")),
    SkillRule("Database", ("database", "sql", "nosql", "schema", "query", "queries"), context_terms=("stored", "queried", "tables", "records", "postgres", "mongodb", "supabase")),
    SkillRule("SQL", ("sql", "sql query", "sql database"), context_terms=("query", "database", "table", "postgres", "schema")),
    SkillRule("PostgreSQL", ("postgresql", "postgres"), tool_terms=("postgresql", "postgres"), task_terms=("queried", "stored", "joined", "indexed"), result_terms=("database", "sql", "schema")),
    SkillRule("MongoDB", ("mongodb", "mongo db", "mongoose"), tool_terms=("mongodb", "mongo db", "mongoose"), task_terms=("queried", "stored", "modeled"), result_terms=("database", "collection", "document")),
    SkillRule("Supabase", ("supabase", "row level security", "rls"), tool_terms=("supabase",), task_terms=("implemented", "queried", "stored"), result_terms=("database", "auth", "postgres", "storage")),
    # Deployment / cloud. Intentionally excludes generic "pipeline".
    SkillRule("Docker", ("docker", "container", "dockerfile"), tool_terms=("docker", "dockerfile"), task_terms=("containerized", "deployed", "built"), result_terms=("container", "image", "service")),
    SkillRule("DevOps", ("docker", "ci/cd", "kubernetes", "deployment pipeline", "cloud deployment", "monitoring", "infrastructure", "github actions", "container", "server", "nginx", "terraform"), context_terms=("deploy", "deployment", "infrastructure", "container", "cloud", "ci/cd", "monitoring", "server", "nginx", "terraform", "github actions")),
    SkillRule("Cloud Deployment", ("cloud deployment", "aws", "gcp", "azure", "vercel", "render.com", "railway"), context_terms=("deploy", "deployment", "cloud", "hosting", "service")),
    SkillRule("CI/CD", ("ci/cd", "github actions", "gitlab ci", "deployment pipeline"), context_terms=("build", "test", "deploy", "workflow", "pipeline")),
    SkillRule("Technical Documentation", ("technical documentation", "project report", "methodology", "results", "limitations"), context_terms=("report", "methodology", "results", "limitations", "documentation", "project")),
)

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


def _matched_phrases(rule: SkillRule, lower: str) -> list[str]:
    if rule.exclude_terms and any(term in lower for term in rule.exclude_terms):
        return []
    hits = [phrase for phrase in rule.phrases if phrase in lower]
    if not hits:
        return []
    if rule.context_terms and not any(term in lower for term in rule.context_terms):
        return []
    return hits


def _confidence(snippet: str, source_type: SourceType, rule: SkillRule | None = None) -> str:
    lower = snippet.lower()
    tool_terms = rule.tool_terms if rule and rule.tool_terms else rule.phrases if rule else ()
    task_terms = rule.task_terms if rule and rule.task_terms else _GENERAL_TASK_TERMS
    result_terms = rule.result_terms if rule and rule.result_terms else _PROJECT_CONTEXT_TERMS
    has_tool = bool(tool_terms) and any(term in lower for term in tool_terms)
    has_task = any(term in lower for term in task_terms)
    has_result = any(term in lower for term in result_terms)
    detail = sum(1 for kw in _GENERAL_TASK_TERMS + _PROJECT_CONTEXT_TERMS if kw in lower)
    if source_type == "certificate_transcript":
        return "medium"
    if has_tool and has_task and has_result:
        return "high"
    if detail >= 2:
        return "high"
    if has_tool or len(snippet.split()) >= 8:
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
            for rule in _SKILL_RULES:
                hits = _matched_phrases(rule, lower)
                if not hits:
                    continue
                skill = rule.skill
                key = (skill, sentence[:120])
                if key in seen:
                    continue
                seen.add(key)
                conf = _confidence(sentence, source_type, rule)
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


class OptionalEvidencePersistError(RuntimeError):
    """Raised when an optional evidence submission could not be persisted."""


class OptionalEvidenceService:
    def __init__(self, db: Any) -> None:
        self._db = db

    def _persist(self, payload: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
        if isinstance(self._db, dict):
            now = datetime.now(UTC).isoformat()
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **payload}
            self._db.setdefault(_TABLE, {})[row["id"]] = row
            return row
        try:
            resp = self._db.table(_TABLE).insert(payload).execute()
            rows = resp.data or []
            if rows:
                return rows[0]
        except Exception as exc:
            if strict:
                raise OptionalEvidencePersistError(str(exc)) from exc
            return payload
        if strict:
            raise OptionalEvidencePersistError("optional_evidence_submissions insert returned no rows")
        return payload

    def submit_file(
        self,
        *,
        user_id: str,
        proof_session_id: str | None,
        file_bytes: bytes,
        filename: str,
        source_type: SourceType = "document",
        extra_metadata: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> dict[str, Any]:
        doc = extract_document_text(file_bytes, filename)
        analysis = analyze_from_extracted_document(doc, source_type=source_type)
        payload: dict[str, Any] = {
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "source_type": source_type,
            "status": analysis.status,
            "file_path": filename,
            "profile_url": None,
            "raw_text": None,
            "analysis_json": {
                **analysis.analysis_json,
                "file_name": doc.file_name,
                "file_type": doc.file_type,
                "extracted_text_preview": doc.preview,
                **(extra_metadata or {}),
            },
            "evidence_objects": analysis.evidence_objects,
        }
        return self._persist(payload, strict=strict)

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
        extra_metadata: dict[str, Any] | None = None,
        strict: bool = False,
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
            "analysis_json": {**analysis.analysis_json, **(extra_metadata or {})},
            "evidence_objects": analysis.evidence_objects,
        }
        return self._persist(payload, strict=strict)

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

    def list_standalone_for_user(
        self, *, user_id: str, source_types: tuple[str, ...] | None = None
    ) -> list[dict[str, Any]]:
        """List standalone (proof_session_id IS NULL) submissions for a user."""
        if isinstance(self._db, dict):
            rows = [
                row
                for row in self._db.get(_TABLE, {}).values()
                if str(row.get("user_id")) == user_id and row.get("proof_session_id") is None
            ]
            if source_types:
                rows = [r for r in rows if r.get("source_type") in source_types]
            rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
            return rows
        try:
            query = (
                self._db.table(_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .is_("proof_session_id", "null")
            )
            if source_types:
                query = query.in_("source_type", list(source_types))
            resp = query.order("created_at", desc=True).execute()
            return resp.data or []
        except Exception:
            return []

    def get_by_id(self, *, user_id: str, evidence_id: str) -> dict[str, Any] | None:
        if isinstance(self._db, dict):
            row = self._db.get(_TABLE, {}).get(evidence_id)
            if not row or str(row.get("user_id")) != user_id:
                return None
            return row
        try:
            resp = (
                self._db.table(_TABLE)
                .select("*")
                .eq("id", evidence_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            return None
