"""Line-level GitHub code evidence segmentation for semantic proof reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SEGMENT_MAX_LINES = 20
_SEGMENT_MIN_LINES = 3

_ML_INITIALIZATION_SIGNALS = (
    "DecisionTreeClassifier",
    "RandomForestClassifier",
    "LogisticRegression",
    "XGBClassifier",
    "SVC",
    "KNeighborsClassifier",
    "GaussianNB",
    "LinearRegression",
    "Ridge",
    "Lasso",
    "RandomForestRegressor",
    "XGBRegressor",
    "model =",
    "classifier =",
    "regressor =",
    "pipeline =",
)
_ML_TRAINING_SIGNALS = (
    "fit(",
    "train_test_split",
    "X_train",
    "y_train",
    "epochs",
    "backward(",
    "optimizer.step",
    "loss.backward",
    "train(",
)
_ML_INFERENCE_SIGNALS = (
    "predict(",
    "predict_proba(",
    "infer(",
    "y_pred",
    "y_predicted",
    "argmax(",
)
_ML_EVALUATION_SIGNALS = (
    "accuracy_score",
    "f1_score",
    "confusion_matrix",
    "classification_report",
    "roc_auc_score",
    "precision_score",
    "recall_score",
    "mean_squared_error",
    "r2_score",
)
_DATA_PREPROCESSING_SIGNALS = (
    "read_csv",
    "dropna",
    "fillna",
    "StandardScaler",
    "MinMaxScaler",
    "LabelEncoder",
    "OneHotEncoder",
    "train_test_split",
    "preprocess",
    "normalize(",
    "astype(",
)
_API_ENDPOINT_SIGNALS = (
    "FastAPI",
    "Flask",
    "@app.get",
    "@app.post",
    "@app.put",
    "@app.delete",
    "@router.get",
    "@router.post",
    "@router.put",
    "@router.delete",
    "app.route(",
    "router = APIRouter",
    "Blueprint(",
)
_DATABASE_SIGNALS = (
    "SQLAlchemy",
    "select(",
    "insert(",
    "update(",
    "delete(",
    "session",
    "db.session",
    "supabase",
    "commit(",
    "create_engine",
    "query(",
)
_UI_SIGNALS = (
    "React",
    "useState",
    "useEffect",
    "useMemo",
    "useCallback",
    "export default function",
    "className=",
    "<div",
    "<button",
    "<span",
    "jsx",
    "tsx",
)
_AUTH_SIGNALS = (
    "login",
    "auth",
    "jwt",
    "token",
    "password",
    "bcrypt",
    "oauth",
    "session",
)
_FILE_IO_SIGNALS = (
    "open(",
    ".read(",
    ".write(",
    "Path(",
    "json.load",
    "json.dump",
    "pickle.load",
    "pickle.dump",
    "csv.reader",
)
_VISUALIZATION_SIGNALS = (
    "matplotlib",
    "seaborn",
    "plt.",
    "plot(",
    "scatter(",
    "bar(",
    "chart",
)

_CATEGORY_PRIORITY = (
    "api_endpoint",
    "database_logic",
    "authentication_logic",
    "ui_component",
    "evaluation_metrics",
    "prediction_inference",
    "model_training",
    "model_initialization",
    "data_preprocessing",
    "visualization",
    "file_io",
    "generic_logic",
    "unknown",
)

_ML_SEGMENT_TYPES = {
    "model_initialization",
    "model_training",
    "prediction_inference",
    "evaluation_metrics",
    "data_preprocessing",
    "visualization",
    "file_io",
}
_BACKEND_SEGMENT_TYPES = {
    "api_endpoint",
    "database_logic",
    "authentication_logic",
    "file_io",
}
_UI_SEGMENT_TYPES = {"ui_component", "file_io", "visualization"}


@dataclass(frozen=True)
class GitHubCodeEvidenceSegment:
    segment_index: int
    line_start: int
    line_end: int
    code_excerpt: str
    segment_type: str
    detected_signals: list[str]
    summary: str
    supports_skill: bool
    confidence_hint: str


@dataclass(frozen=True)
class GitHubCodeEvidenceSegmentationResult:
    available: bool
    skill_name: str
    total_segments: int
    segments: list[GitHubCodeEvidenceSegment]
    overall_summary: str
    notes: str | None = None


def segment_github_code_evidence(
    source_code: str | None,
    line_start: int | None,
    skill_name: str,
    evidence_description: str | None = None,
) -> GitHubCodeEvidenceSegmentationResult:
    skill = (skill_name or "").strip()
    normalized_code = _normalize_code(source_code or "")
    if not normalized_code.strip():
        return GitHubCodeEvidenceSegmentationResult(
            available=False,
            skill_name=skill,
            total_segments=0,
            segments=[],
            overall_summary="No GitHub code was available for segmentation.",
            notes="The selected GitHub code range was empty or unavailable.",
        )

    start_line = line_start or 1
    lines = normalized_code.splitlines()
    grouped_segments = _build_segments(lines, start_line, skill, evidence_description)
    overall_summary = _build_overall_summary(skill, grouped_segments)
    notes = None
    if not any(segment.supports_skill for segment in grouped_segments):
        notes = "No strong skill-specific code signals were found; segmentation is conservative."

    return GitHubCodeEvidenceSegmentationResult(
        available=True,
        skill_name=skill,
        total_segments=len(grouped_segments),
        segments=grouped_segments,
        overall_summary=overall_summary,
        notes=notes,
    )


def github_code_evidence_segmentation_to_snapshot(
    result: GitHubCodeEvidenceSegmentationResult | dict[str, Any] | None,
) -> dict[str, Any]:
    if result is None:
        return {
            "available": False,
            "overall_summary": "",
            "total_segments": 0,
            "segments": [],
            "notes": None,
        }
    if isinstance(result, dict):
        segments = [github_code_evidence_segment_to_snapshot(segment) for segment in result.get("segments") or []]
        return {
            "available": bool(result.get("available")),
            "skill_name": result.get("skill_name") or "",
            "total_segments": int(result.get("total_segments") or len(segments)),
            "segments": segments,
            "overall_summary": str(result.get("overall_summary") or ""),
            "notes": result.get("notes"),
        }
    return {
        "available": result.available,
        "skill_name": result.skill_name,
        "total_segments": result.total_segments,
        "segments": [github_code_evidence_segment_to_snapshot(segment) for segment in result.segments],
        "overall_summary": result.overall_summary,
        "notes": result.notes,
    }


def github_code_evidence_segment_to_snapshot(segment: GitHubCodeEvidenceSegment | dict[str, Any]) -> dict[str, Any]:
    if isinstance(segment, dict):
        return {
            "segment_index": segment.get("segment_index"),
            "line_start": segment.get("line_start"),
            "line_end": segment.get("line_end"),
            "segment_type": segment.get("segment_type") or "unknown",
            "detected_signals": list(segment.get("detected_signals") or []),
            "summary": segment.get("summary") or "",
            "supports_skill": bool(segment.get("supports_skill")),
            "confidence_hint": segment.get("confidence_hint") or "low",
        }
    return {
        "segment_index": segment.segment_index,
        "line_start": segment.line_start,
        "line_end": segment.line_end,
        "segment_type": segment.segment_type,
        "detected_signals": list(segment.detected_signals),
        "summary": segment.summary,
        "supports_skill": segment.supports_skill,
        "confidence_hint": segment.confidence_hint,
    }


def _build_segments(
    lines: list[str],
    start_line: int,
    skill_name: str,
    evidence_description: str | None,
) -> list[GitHubCodeEvidenceSegment]:
    blocks = _split_into_blocks(lines, start_line)
    segments: list[GitHubCodeEvidenceSegment] = []
    segment_index = 1

    for block in blocks:
        block_segments = _split_block_into_segments(block, skill_name, evidence_description)
        for block_segment in block_segments:
            for chunk in _chunk_segment(block_segment, _SEGMENT_MAX_LINES):
                lines_only = chunk["lines"]
                absolute_start = chunk["line_start"]
                absolute_end = chunk["line_end"]
                excerpt = "\n".join(line["text"] for line in lines_only).strip("\n")
                classified = _classify_segment(lines_only, skill_name, evidence_description)
                segments.append(
                    GitHubCodeEvidenceSegment(
                        segment_index=segment_index,
                        line_start=absolute_start,
                        line_end=absolute_end,
                        code_excerpt=excerpt,
                        segment_type=classified["segment_type"],
                        detected_signals=classified["detected_signals"],
                        summary=classified["summary"],
                        supports_skill=classified["supports_skill"],
                        confidence_hint=classified["confidence_hint"],
                    )
                )
                segment_index += 1

    if not segments:
        return [
            GitHubCodeEvidenceSegment(
                segment_index=1,
                line_start=start_line,
                line_end=start_line + max(len(lines) - 1, 0),
                code_excerpt="\n".join(lines).strip(),
                segment_type="unknown",
                detected_signals=[],
                summary="The selected code could not be confidently segmented.",
                supports_skill=False,
                confidence_hint="low",
            )
        ]
    return segments


def _split_into_blocks(lines: list[str], start_line: int) -> list[list[dict[str, Any]]]:
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for offset, line in enumerate(lines):
        absolute_line = start_line + offset
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append({"line": absolute_line, "text": line})
    if current:
        blocks.append(current)
    return blocks


def _split_block_into_segments(
    block: list[dict[str, Any]],
    skill_name: str,
    evidence_description: str | None,
) -> list[list[dict[str, Any]]]:
    if len(block) <= _SEGMENT_MIN_LINES:
        return [block]

    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_type = "unknown"
    for line in block:
        line_type, _, _ = _classify_line(line["text"], skill_name, evidence_description)
        if not current:
            current = [line]
            current_type = line_type
            continue

        should_split = _should_start_new_segment(current_type, line_type, current)
        if should_split:
            segments.append(current)
            current = [line]
            current_type = line_type
        else:
            current.append(line)
            if current_type == "unknown" and line_type != "unknown":
                current_type = line_type

    if current:
        segments.append(current)
    return segments


def _should_start_new_segment(current_type: str, next_type: str, current_lines: list[dict[str, Any]]) -> bool:
    if len(current_lines) < 1:
        return False
    if len(current_lines) >= _SEGMENT_MAX_LINES:
        return True
    if next_type == "unknown":
        return False
    if current_type == "unknown":
        return True
    if current_type == next_type:
        return False
    if current_type == "generic_logic" and next_type != "generic_logic":
        return True
    if next_type == "generic_logic" and current_type != "generic_logic":
        return False
    return current_type != next_type


def _chunk_segment(segment_lines: list[dict[str, Any]], max_lines: int) -> list[dict[str, Any]]:
    if len(segment_lines) <= max_lines:
        return [
            {
                "lines": segment_lines,
                "line_start": segment_lines[0]["line"],
                "line_end": segment_lines[-1]["line"],
            }
        ]

    chunks: list[dict[str, Any]] = []
    for index in range(0, len(segment_lines), max_lines):
        chunk_lines = segment_lines[index : index + max_lines]
        chunks.append(
            {
                "lines": chunk_lines,
                "line_start": chunk_lines[0]["line"],
                "line_end": chunk_lines[-1]["line"],
            }
        )
    return chunks


def _classify_segment(
    lines: list[dict[str, Any]],
    skill_name: str,
    evidence_description: str | None,
) -> dict[str, Any]:
    detections: list[tuple[str, list[str]]] = []
    for line in lines:
        detections.append(_line_signals(line["text"]))

    detected_signals: list[str] = []
    segment_type = "unknown"
    for candidate_type in _CATEGORY_PRIORITY:
        if any(candidate_type == line_type for line_type, _ in detections):
            segment_type = candidate_type
            break

    for _, signals in detections:
        for signal in signals:
            if signal not in detected_signals:
                detected_signals.append(signal)

    summary = _build_segment_summary(segment_type, detected_signals, skill_name, lines)
    supports_skill = _supports_skill(skill_name, segment_type, detected_signals, evidence_description, lines)
    confidence_hint = _confidence_hint(segment_type, detected_signals, supports_skill)
    return {
        "segment_type": segment_type,
        "detected_signals": detected_signals,
        "summary": summary,
        "supports_skill": supports_skill,
        "confidence_hint": confidence_hint,
    }


def _line_signals(line: str) -> tuple[str, list[str]]:
    text = line.strip()
    lower = text.lower()
    if not text:
        return "unknown", []

    matches = _match_signals(text, _API_ENDPOINT_SIGNALS)
    if matches:
        return "api_endpoint", matches

    matches = _match_signals(text, _DATABASE_SIGNALS)
    if matches:
        return "database_logic", matches

    matches = _match_signals(text, _AUTH_SIGNALS)
    if matches:
        return "authentication_logic", matches

    matches = _match_signals(text, _UI_SIGNALS)
    if matches:
        return "ui_component", matches

    matches = _match_signals(text, _ML_EVALUATION_SIGNALS)
    if matches:
        return "evaluation_metrics", matches

    matches = _match_signals(text, _ML_INFERENCE_SIGNALS)
    if matches:
        return "prediction_inference", matches

    matches = _match_signals(text, _ML_TRAINING_SIGNALS)
    if matches:
        return "model_training", matches

    matches = _match_signals(text, _ML_INITIALIZATION_SIGNALS)
    if matches:
        return "model_initialization", matches

    matches = _match_signals(text, _DATA_PREPROCESSING_SIGNALS)
    if matches:
        return "data_preprocessing", matches

    matches = _match_signals(text, _VISUALIZATION_SIGNALS)
    if matches:
        return "visualization", matches

    matches = _match_signals(text, _FILE_IO_SIGNALS)
    if matches:
        return "file_io", matches

    if re.match(r"^\s*(def|class|for|while|if|elif|else|return|try|except|with)\b", text):
        return "generic_logic", [text.split("(", 1)[0].strip()]

    if any(token in lower for token in ("=", ":", "->")):
        return "generic_logic", [text.split("=", 1)[0].strip() or "assignment"]

    return "unknown", []


def _classify_line(line: str, skill_name: str, evidence_description: str | None) -> tuple[str, list[str], str]:
    segment_type, signals = _line_signals(line)
    return segment_type, signals, line


def _match_signals(line: str, signals: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    lowered = line.lower()
    for signal in signals:
        if signal.lower() in lowered:
            matches.append(signal)
    return matches


def _build_segment_summary(
    segment_type: str,
    detected_signals: list[str],
    skill_name: str,
    lines: list[dict[str, Any]],
) -> str:
    if segment_type == "model_initialization":
        model_name = _extract_model_name(detected_signals, lines) or "a machine learning model"
        return f"Initializes {model_name} for the selected machine learning workflow."
    if segment_type == "model_training":
        return "Trains the model using the prepared training data."
    if segment_type == "prediction_inference":
        return "Generates predictions from the trained model."
    if segment_type == "evaluation_metrics":
        metrics = _human_join([_pretty_signal(signal) for signal in detected_signals[:3]])
        if metrics:
            return f"Evaluates model performance using {metrics}."
        return "Evaluates model performance using standard classification metrics."
    if segment_type == "data_preprocessing":
        return "Prepares the input data before model training or prediction."
    if segment_type == "api_endpoint":
        return "Defines an API route that exposes backend application logic."
    if segment_type == "database_logic":
        return "Implements database query or persistence logic."
    if segment_type == "ui_component":
        return "Defines a user interface component and its rendered UI logic."
    if segment_type == "authentication_logic":
        return "Handles authentication or session-management logic."
    if segment_type == "visualization":
        return "Produces a chart or visualization for the workflow."
    if segment_type == "file_io":
        return "Reads or writes files used by the application."
    if segment_type == "generic_logic":
        return f"Contains general implementation logic related to {skill_name or 'the selected skill'}."
    return "Contains code that could not be confidently classified."


def _build_overall_summary(skill_name: str, segments: list[GitHubCodeEvidenceSegment]) -> str:
    segment_types = [segment.segment_type for segment in segments if segment.supports_skill]

    if any(segment_type in _ML_SEGMENT_TYPES for segment_type in segment_types):
        parts: list[str] = []
        if "data_preprocessing" in segment_types:
            parts.append("data preparation")
        if "model_initialization" in segment_types:
            parts.append("model setup")
        if "model_training" in segment_types:
            parts.append("training")
        if "prediction_inference" in segment_types:
            parts.append("prediction")
        if "evaluation_metrics" in segment_types:
            parts.append("evaluation")
        if "visualization" in segment_types:
            parts.append("visualization")
        if not parts:
            parts.append("machine learning logic")
        return f"The selected code demonstrates a machine learning workflow that includes {_human_join(parts)}."

    if "api_endpoint" in segment_types or "database_logic" in segment_types or "authentication_logic" in segment_types:
        parts = []
        if "api_endpoint" in segment_types:
            parts.append("API route handling")
        if "database_logic" in segment_types:
            parts.append("database access")
        if "authentication_logic" in segment_types:
            parts.append("authentication logic")
        if not parts:
            parts.append("backend application logic")
        return f"The selected code defines backend logic that includes {_human_join(parts)}."

    if "ui_component" in segment_types:
        return "The selected code defines a user interface component with frontend rendering logic."

    if "file_io" in segment_types:
        return "The selected code demonstrates file-handling logic that supports the selected proof."

    return f"The selected code contains general implementation logic related to {skill_name or 'the selected skill'}."


def _supports_skill(
    skill_name: str,
    segment_type: str,
    detected_signals: list[str],
    evidence_description: str | None,
    lines: list[dict[str, Any]],
) -> bool:
    skill = skill_name.lower()
    if not detected_signals:
        return False
    if any(term in skill for term in ("machine learning", "ml", "data science", "artificial intelligence", "ai", "deep learning")):
        return segment_type in _ML_SEGMENT_TYPES
    if any(term in skill for term in ("fastapi", "flask", "api", "backend", "server")):
        return segment_type in _BACKEND_SEGMENT_TYPES
    if any(term in skill for term in ("react", "frontend", "javascript", "typescript", "ui")):
        return segment_type in _UI_SEGMENT_TYPES
    if any(term in skill for term in ("sql", "database", "supabase", "postgres")):
        return segment_type in {"database_logic", "file_io"}
    if "python" in skill:
        return segment_type != "unknown"
    return segment_type not in {"unknown", "generic_logic"} or len(detected_signals) >= 2


def _confidence_hint(segment_type: str, detected_signals: list[str], supports_skill: bool) -> str:
    if not supports_skill:
        return "low"
    if segment_type in {"model_initialization", "model_training", "prediction_inference", "evaluation_metrics", "api_endpoint", "database_logic", "ui_component"} and len(detected_signals) >= 2:
        return "high"
    if segment_type in {"model_initialization", "model_training", "prediction_inference", "evaluation_metrics", "api_endpoint", "database_logic", "ui_component"}:
        return "medium"
    if len(detected_signals) >= 2:
        return "medium"
    return "low"


def _extract_model_name(detected_signals: list[str], lines: list[dict[str, Any]]) -> str | None:
    for signal in detected_signals:
        if signal.endswith("Classifier") or signal.endswith("Regressor"):
            return _humanize_identifier(signal)
    code = "\n".join(line["text"] for line in lines)
    match = re.search(r"\b([A-Z][A-Za-z0-9_]*(Classifier|Regressor|Model))\b", code)
    if match:
        return _humanize_identifier(match.group(1))
    return None


def _humanize_identifier(value: str) -> str:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    spaced = spaced.replace("_", " ")
    return re.sub(r"\s+", " ", spaced).strip()


def _pretty_signal(signal: str) -> str:
    signal = signal.strip()
    if signal.endswith("("):
        signal = signal[:-1]
    return _humanize_identifier(signal)


def _human_join(parts: list[str]) -> str:
    cleaned = [part for part in (part.strip() for part in parts) if part]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _normalize_code(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").splitlines()).strip("\n")
