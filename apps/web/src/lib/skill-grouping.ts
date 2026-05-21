/**
 * skill-grouping.ts — Phase J3C + J4A
 * Hierarchical skill grouping, subskill extraction, confidence calculation,
 * and system graph building.
 *
 * groupProofSuggestions() — groups raw scan candidates (pre-import, J3C)
 * groupSavedEvidence()    — groups saved DB evidence (post-import, J4A)
 */

import type { GitHubPortfolioScanCandidate, SkillEvidenceResponse } from "./api"

// ── Types ─────────────────────────────────────────────────────────────────────

export type SkillEvidenceType =
  | "code"
  | "dockerfile"
  | "workflow"
  | "api_file"
  | "data_file"
  | "ui_file"
  | "deployment_config"
  | "metrics_config"
  | "model_file"
  | "other"

export type ConfidenceLevel = "high" | "medium" | "low"

export type EvidenceSource =
  | "github"
  | "website"
  | "linkedin"
  | "certificate"
  | "youtube"
  | "pdf"
  | "portfolio"
  | "manual"
  | "google_drive"
  | "other"

export type SkillEvidence = {
  candidateId: string
  repoName: string
  repoUrl: string
  projectTitle: string
  filePath: string
  lineStart: number
  lineEnd: number
  githubHighlightUrl: string
  selectionReason: string
  evidenceDescription: string
  confidence: "high" | "medium" | "low"
  suggestedStatus: string
  evidenceType: SkillEvidenceType
  skillLabel: string
  evidenceSource: EvidenceSource
  /** Source-specific display data (timestamps, page numbers, etc.) */
  displayMetadata?: Record<string, unknown>
}

export type ProjectEvidenceGroup = {
  repoName: string
  repoUrl: string
  projectTitle: string
  evidenceItems: SkillEvidence[]
}

export type SkillSubskill = {
  name: string
  evidenceCount: number
}

export type SkillGraphNode = {
  id: string
  label: string
  nodeType: string
  evidenceCount: number
  confidence: ConfidenceLevel
  evidenceItemIds: string[]
  description: string
  hasEvidence: boolean
}

export type SkillGraphEdge = {
  id: string
  from: string
  to: string
  relationshipLabel: string
}

export type SkillSystemGraph = {
  id: string
  skillId: string
  title: string
  summary: string
  nodes: SkillGraphNode[]
  edges: SkillGraphEdge[]
  confidence: ConfidenceLevel
  needsReview: boolean
}

export type GroupedSkillSuggestion = {
  id: string
  skillName: string
  normalizedSkillName: string
  category: string
  parentSkill: string | null
  confidence: ConfidenceLevel
  statusSummary: string
  evidenceCount: number
  repoCount: number
  repositories: string[]
  subskills: SkillSubskill[]
  evidenceItems: SkillEvidence[]
  projectGroups: ProjectEvidenceGroup[]
  systemGraph: SkillSystemGraph | null
}

// ── Normalization ─────────────────────────────────────────────────────────────

export function normalizeSkillName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9\-/]/g, "")
}

export function mapSkillToCategory(skillName: string): string {
  const l = skillName.toLowerCase()
  if (l.includes("machine learning") || l.includes("deep learning") || l.includes("computer vision")) return "AI / ML"
  if (l.includes("nlp") || l.includes("language processing") || l.includes("llm") || l.includes("rag")) return "AI / ML"
  if (l.includes("backend") || l.includes("api")) return "Backend"
  if (l.includes("full-stack") || l.includes("react") || l.includes("frontend")) return "Frontend"
  if (l.includes("mlops")) return "Operations"
  if (l.includes("devops") || l.includes("ci-cd") || l.includes("ci/cd")) return "Operations"
  if (l.includes("cloud") || l.includes("deployment")) return "Cloud"
  if (l.includes("monitoring") || l.includes("observability")) return "Operations"
  if (l.includes("data")) return "Data"
  if (l.includes("game")) return "Game"
  if (l.includes("systems")) return "Systems"
  return "General"
}

// ── Skill → parent category mapping ──────────────────────────────────────────

// Unambiguous: skill_label directly maps to a parent category
const SKILL_LABEL_TO_PARENT: Record<string, string> = {
  "Machine Learning": "Machine Learning Engineering",
  "FastAPI": "Backend / API Engineering",
  "Docker": "MLOps",
  "CI/CD": "DevOps / CI-CD",
  "React": "Full-Stack Development",
  "TypeScript": "Full-Stack Development",
  "JavaScript": "Full-Stack Development",
  "Web Development": "Full-Stack Development",
  "GCP": "Cloud Deployment",
  "AWS": "Cloud Deployment",
  "Azure": "Cloud Deployment",
  "Cloud Deployment": "Cloud Deployment",
  "MLOps": "MLOps",
  "Computer Vision": "Computer Vision",
  "NLP": "NLP / Language Processing",
  "RAG / LLM": "AI / LLM Engineering",
  "Data Engineering": "Data Engineering",
  "PostgreSQL": "Backend / API Engineering",
  "SQL": "Data Engineering",
  "Kubernetes": "DevOps / CI-CD",
  "Shell Scripting": "DevOps / CI-CD",
  "Go": "Backend / API Engineering",
  "Java": "Backend / API Engineering",
  "Rust": "Systems Engineering",
  "C++": "Systems Engineering",
  "Deep Learning": "Machine Learning Engineering",
  "R": "Data Engineering",
  "Julia": "Machine Learning Engineering",
}

// For ambiguous skill labels (like "Python"), use the detection reason
const DETECTION_REASON_TO_PARENT: Record<string, string> = {
  "ML training call": "Machine Learning Engineering",
  "ML prediction/inference": "Machine Learning Engineering",
  "ML model instantiation": "Machine Learning Engineering",
  "ML evaluation metrics": "Machine Learning Engineering",
  "API endpoint decorator": "Backend / API Engineering",
  "API handler function": "Backend / API Engineering",
  "Database query": "Backend / API Engineering",
  "Dockerfile instruction": "MLOps",
  "CI/CD workflow step": "DevOps / CI-CD",
  "Cloud deployment command": "Cloud Deployment",
  "RAG/LLM logic": "AI / LLM Engineering",
  "NLP processing": "NLP / Language Processing",
  "React component logic": "Full-Stack Development",
  "Monitoring/metrics": "Monitoring / Observability",
  "Data preprocessing": "Data Engineering",
}

function inferParentFromFilePath(filePath: string): string | undefined {
  const lower = filePath.toLowerCase()
  const filename = lower.split("/").pop() ?? ""
  if (filename === "dockerfile" || filename.startsWith("dockerfile.")) return "MLOps"
  if (lower.includes(".github/workflows/")) return "DevOps / CI-CD"
  if (["train.py", "training.py", "model.py", "fit.py", "train.ipynb"].includes(filename)) return "Machine Learning Engineering"
  if (["predict.py", "inference.py", "infer.py"].includes(filename)) return "Machine Learning Engineering"
  if (["app.py", "main.py", "api.py", "server.py", "routes.py", "endpoints.py"].includes(filename)) return "Backend / API Engineering"
  if (["prometheus.yml", "prometheus.yaml"].includes(filename)) return "Monitoring / Observability"
  if (["docker-compose.yml", "docker-compose.yaml"].includes(filename)) return "MLOps"
  if (lower.includes("preprocess") || lower.includes("data_clean") || lower.includes("feature_eng")) return "Data Engineering"
  if (lower.endsWith(".tsx") || lower.endsWith(".jsx")) return "Full-Stack Development"
  return undefined
}

function resolveParentCategory(c: GitHubPortfolioScanCandidate): string {
  const direct = SKILL_LABEL_TO_PARENT[c.skill_label]
  if (direct) return direct
  const fromReason = DETECTION_REASON_TO_PARENT[c.selection_reason]
  if (fromReason) return fromReason
  const fromPath = inferParentFromFilePath(c.file_path)
  if (fromPath) return fromPath
  return c.skill_label // fallback: preserve original label
}

// ── Evidence type inference ───────────────────────────────────────────────────

export function inferEvidenceType(filePath: string, detectionReason: string): SkillEvidenceType {
  const lower = filePath.toLowerCase()
  const filename = lower.split("/").pop() ?? ""
  if (filename === "dockerfile" || filename.startsWith("dockerfile.")) return "dockerfile"
  if (lower.includes(".github/workflows/")) return "workflow"
  if (filename.includes("prometheus") || detectionReason === "Monitoring/metrics") return "metrics_config"
  if (filename.includes("docker-compose")) return "deployment_config"
  if (lower.endsWith(".yaml") && !lower.includes(".github/workflows") && !filename.includes("prometheus")) return "deployment_config"
  if (lower.endsWith(".tsx") || lower.endsWith(".jsx")) return "ui_file"
  if (["train.py", "model.py", "predict.py", "inference.py", "fit.py"].includes(filename)) return "model_file"
  if (lower.includes("data") || lower.includes("preprocess") || lower.endsWith(".csv")) return "data_file"
  if (["app.py", "main.py", "api.py", "server.py", "routes.py", "endpoints.py"].includes(filename)) return "api_file"
  if (lower.endsWith(".py") || lower.endsWith(".ts") || lower.endsWith(".js") || lower.endsWith(".go")) return "code"
  return "other"
}

// ── Subskill name extraction ──────────────────────────────────────────────────

const REASON_TO_SUBSKILL: Record<string, string> = {
  "ML training call": "Model Training",
  "ML prediction/inference": "Model Inference",
  "ML model instantiation": "Model Instantiation",
  "ML evaluation metrics": "Model Evaluation",
  "API endpoint decorator": "FastAPI / API Endpoints",
  "API handler function": "Request Handlers",
  "Dockerfile instruction": "Docker",
  "CI/CD workflow step": "CI/CD Pipeline",
  "Cloud deployment command": "Cloud Deployment",
  "Database query": "Database Operations",
  "RAG/LLM logic": "LLM / RAG",
  "NLP processing": "NLP Processing",
  "React component logic": "React Components",
  "Monitoring/metrics": "Prometheus Metrics",
  "Data preprocessing": "Data Preprocessing",
}

function getSubskillName(skillLabel: string, selectionReason: string): string {
  // Use specific labels as-is (already meaningful)
  if (!["Python", "JavaScript", "TypeScript"].includes(skillLabel)) return skillLabel
  return REASON_TO_SUBSKILL[selectionReason] ?? skillLabel
}

// ── Confidence calculation ────────────────────────────────────────────────────

const STRONG_DETECTION_REASONS = new Set([
  "ML training call",
  "ML prediction/inference",
  "ML model instantiation",
  "ML evaluation metrics",
  "API endpoint decorator",
  "Dockerfile instruction",
  "CI/CD workflow step",
  "RAG/LLM logic",
  "NLP processing",
  "Monitoring/metrics",
])

const STRONG_EVIDENCE_TYPES = new Set<SkillEvidenceType>([
  "dockerfile",
  "workflow",
  "model_file",
  "api_file",
  "metrics_config",
  "deployment_config",
])

export function calculateSkillConfidence(evidenceItems: SkillEvidence[]): ConfidenceLevel {
  if (evidenceItems.length === 0) return "low"
  const repos = new Set(evidenceItems.map((e) => e.repoName))
  const strongCount = evidenceItems.filter(
    (e) => STRONG_DETECTION_REASONS.has(e.selectionReason) || STRONG_EVIDENCE_TYPES.has(e.evidenceType)
  ).length

  if (repos.size >= 2 && strongCount >= 1) return "high"
  if (strongCount >= 3) return "high"
  if (strongCount >= 1) return "medium"
  if (evidenceItems.length >= 5) return "medium"
  return "low"
}

// ── Skill System Graph builder ────────────────────────────────────────────────

type GraphNodeTemplate = {
  id: string
  label: string
  nodeType: string
  description: string
  matchReasons: string[]
  matchFilePatterns: string[]
  matchSkillLabels: string[]
}

type GraphTemplate = {
  title: string
  summary: string
  nodes: GraphNodeTemplate[]
}

const GRAPH_TEMPLATES: Record<string, GraphTemplate> = {
  "MLOps": {
    title: "MLOps System Graph",
    summary: "End-to-end MLOps pipeline: model artifacts → serving API → container → CI/CD → cloud → monitoring.",
    nodes: [
      { id: "data-model", label: "Data / Model Artifacts", nodeType: "input", description: "Training data and serialized model files", matchReasons: ["ML training call", "ML model instantiation"], matchFilePatterns: ["train", "model", ".pkl", "joblib"], matchSkillLabels: ["Machine Learning"] },
      { id: "serving-api", label: "Model Serving API", nodeType: "service", description: "FastAPI or Flask serving layer for model inference", matchReasons: ["API endpoint decorator", "API handler function"], matchFilePatterns: ["app.py", "api.py", "main.py", "server.py"], matchSkillLabels: ["FastAPI"] },
      { id: "docker", label: "Docker Container", nodeType: "infrastructure", description: "Containerized application for portable deployment", matchReasons: ["Dockerfile instruction"], matchFilePatterns: ["dockerfile"], matchSkillLabels: ["Docker"] },
      { id: "cicd", label: "CI/CD Pipeline", nodeType: "automation", description: "Automated build, test, and deployment pipeline", matchReasons: ["CI/CD workflow step"], matchFilePatterns: [".github/workflows", "workflow"], matchSkillLabels: ["CI/CD"] },
      { id: "cloud", label: "Cloud Deployment", nodeType: "deployment", description: "Production cloud deployment target (Cloud Run, Render, etc.)", matchReasons: ["Cloud deployment command"], matchFilePatterns: ["cloud-run", "render", "kubernetes"], matchSkillLabels: ["GCP", "AWS"] },
      { id: "monitoring", label: "Monitoring / Logging", nodeType: "observability", description: "Metrics collection and observability stack", matchReasons: ["Monitoring/metrics"], matchFilePatterns: ["prometheus", "grafana", "metrics"], matchSkillLabels: ["MLOps"] },
    ],
  },
  "Machine Learning Engineering": {
    title: "Machine Learning Engineering System Graph",
    summary: "Full ML pipeline: dataset → preprocessing → training → evaluation → inference.",
    nodes: [
      { id: "dataset", label: "Dataset", nodeType: "input", description: "Raw data loading and ingestion", matchReasons: ["Data preprocessing"], matchFilePatterns: ["data", "dataset", ".csv"], matchSkillLabels: [] },
      { id: "preprocess", label: "Preprocessing", nodeType: "transform", description: "Data cleaning, normalization, and transformation", matchReasons: ["Data preprocessing"], matchFilePatterns: ["preprocess", "clean", "feature"], matchSkillLabels: [] },
      { id: "training", label: "Model Training / Artifact", nodeType: "compute", description: "Model training and serialization to disk", matchReasons: ["ML training call", "ML model instantiation"], matchFilePatterns: ["train", "model", "fit"], matchSkillLabels: ["Machine Learning"] },
      { id: "evaluation", label: "Evaluation", nodeType: "validation", description: "Model performance metrics and scoring", matchReasons: ["ML evaluation metrics"], matchFilePatterns: ["evaluate", "metrics", "score", "report"], matchSkillLabels: [] },
      { id: "inference", label: "Inference / API / UI", nodeType: "output", description: "Prediction serving via API or interactive UI", matchReasons: ["ML prediction/inference", "API endpoint decorator"], matchFilePatterns: ["predict", "inference", "app", "api"], matchSkillLabels: [] },
    ],
  },
  "Computer Vision": {
    title: "Computer Vision System Graph",
    summary: "Image/video processing pipeline: input → detection → extraction → inference → UI.",
    nodes: [
      { id: "input", label: "Image / Webcam Input", nodeType: "input", description: "Image upload or live webcam stream input", matchReasons: [], matchFilePatterns: ["webcam", "camera", "image", "upload", "video"], matchSkillLabels: ["Computer Vision"] },
      { id: "detection", label: "Pose / Object Detection", nodeType: "compute", description: "Detection model inference (DETR, MediaPipe, YOLO)", matchReasons: ["ML model instantiation", "ML prediction/inference"], matchFilePatterns: ["detect", "pose", "yolo", "detr", "mediapipe", "object"], matchSkillLabels: ["Computer Vision"] },
      { id: "extraction", label: "Feature Extraction", nodeType: "transform", description: "Landmark or bounding box feature extraction", matchReasons: [], matchFilePatterns: ["feature", "extract", "landmark"], matchSkillLabels: [] },
      { id: "classifier", label: "Classifier / Inference", nodeType: "compute", description: "Classification or inference result computation", matchReasons: ["ML prediction/inference", "ML evaluation metrics"], matchFilePatterns: ["model", "infer", "predict", "classify"], matchSkillLabels: [] },
      { id: "ui", label: "UI Feedback", nodeType: "output", description: "Results displayed in Gradio, Streamlit, or React UI", matchReasons: ["React component logic"], matchFilePatterns: [".tsx", ".jsx", "gradio", "streamlit", "app.py", "demo"], matchSkillLabels: ["React"] },
    ],
  },
  "Monitoring / Observability": {
    title: "Monitoring / Observability System Graph",
    summary: "Full observability stack: services → /metrics → Prometheus → Grafana Cloud.",
    nodes: [
      { id: "services", label: "QA / App Services", nodeType: "input", description: "Services being monitored", matchReasons: ["API endpoint decorator"], matchFilePatterns: ["api.py", "app.py", "qa", "service"], matchSkillLabels: [] },
      { id: "metrics", label: "Metrics Endpoints", nodeType: "service", description: "Prometheus-compatible /metrics HTTP endpoints", matchReasons: ["Monitoring/metrics"], matchFilePatterns: ["metrics", "exporter", "counter", "gauge"], matchSkillLabels: ["MLOps"] },
      { id: "prometheus", label: "Prometheus", nodeType: "infrastructure", description: "Metrics collection and time-series storage", matchReasons: ["Monitoring/metrics"], matchFilePatterns: ["prometheus.yml", "prometheus.yaml", "prometheus"], matchSkillLabels: [] },
      { id: "node-exporter", label: "node-exporter", nodeType: "agent", description: "Host-level system metrics exporter", matchReasons: [], matchFilePatterns: ["docker-compose", "node-exporter", "node_exporter"], matchSkillLabels: [] },
      { id: "grafana", label: "Grafana Cloud remote_write", nodeType: "dashboard", description: "Remote metrics storage and visualization dashboard", matchReasons: [], matchFilePatterns: ["grafana", "remote_write", "remote-write"], matchSkillLabels: [] },
      { id: "debug", label: "Debugging / Inspection", nodeType: "output", description: "Operational debugging and service inspection", matchReasons: [], matchFilePatterns: [], matchSkillLabels: [] },
    ],
  },
  "Backend / API Engineering": {
    title: "Backend / API Engineering System Graph",
    summary: "API server architecture: request → route → validation → logic → response.",
    nodes: [
      { id: "route", label: "API Route", nodeType: "routing", description: "Route definition and HTTP method dispatch", matchReasons: ["API endpoint decorator"], matchFilePatterns: ["routes.py", "endpoints.py", "api.py", "router"], matchSkillLabels: ["FastAPI"] },
      { id: "validation", label: "Validation", nodeType: "middleware", description: "Input validation with Pydantic schemas", matchReasons: ["API handler function"], matchFilePatterns: ["schema", "model", "pydantic"], matchSkillLabels: [] },
      { id: "logic", label: "Business Logic / Model", nodeType: "compute", description: "Core request processing or model inference", matchReasons: ["ML prediction/inference", "ML training call"], matchFilePatterns: ["service", "logic", "handler"], matchSkillLabels: [] },
      { id: "db", label: "Database", nodeType: "data", description: "Data persistence layer", matchReasons: ["Database query"], matchFilePatterns: ["db", "database", "supabase", "postgres"], matchSkillLabels: ["PostgreSQL"] },
      { id: "response", label: "JSON Response", nodeType: "output", description: "Structured API response output", matchReasons: [], matchFilePatterns: [], matchSkillLabels: [] },
    ],
  },
  "Full-Stack Development": {
    title: "Full-Stack Development System Graph",
    summary: "Complete app: backend API → React components → state → user output.",
    nodes: [
      { id: "backend", label: "Backend / API", nodeType: "service", description: "API server or prediction service", matchReasons: ["API endpoint decorator"], matchFilePatterns: ["api.py", "app.py", "main.py", "server.py"], matchSkillLabels: ["FastAPI"] },
      { id: "components", label: "UI Components", nodeType: "ui", description: "React or Next.js component library", matchReasons: ["React component logic"], matchFilePatterns: [".tsx", ".jsx"], matchSkillLabels: ["React", "TypeScript", "JavaScript"] },
      { id: "state", label: "State / Data Flow", nodeType: "ui", description: "Application state management (useState, hooks)", matchReasons: ["React component logic"], matchFilePatterns: ["hook", "store", "context"], matchSkillLabels: [] },
      { id: "output", label: "User Output / Charts", nodeType: "output", description: "Data visualization and user-facing results", matchReasons: [], matchFilePatterns: ["chart", "recharts", "plot", "graph"], matchSkillLabels: [] },
    ],
  },
  "Cloud Deployment": {
    title: "Cloud Deployment System Graph",
    summary: "Deployment pipeline: code → Dockerfile → cloud runtime → public endpoint.",
    nodes: [
      { id: "docker", label: "Dockerfile / Build", nodeType: "build", description: "Container image build configuration", matchReasons: ["Dockerfile instruction"], matchFilePatterns: ["dockerfile"], matchSkillLabels: ["Docker"] },
      { id: "runtime", label: "Cloud Runtime", nodeType: "deployment", description: "Managed cloud runtime (Cloud Run, Render, etc.)", matchReasons: ["Cloud deployment command"], matchFilePatterns: ["cloud-run", "render", "kubernetes", "app.yaml"], matchSkillLabels: ["GCP", "AWS"] },
      { id: "secrets", label: "Secrets / Env Variables", nodeType: "config", description: "Secure configuration and secrets management", matchReasons: [], matchFilePatterns: ["secret", ".env", "secret-manager"], matchSkillLabels: [] },
      { id: "endpoint", label: "Public Endpoint", nodeType: "output", description: "Public-facing deployed URL", matchReasons: [], matchFilePatterns: [], matchSkillLabels: [] },
    ],
  },
  "Game AI": {
    title: "Game AI System Graph",
    summary: "CNN-based game agent: game state → model → action logits → execution.",
    nodes: [
      { id: "game-state", label: "Game State / Frame Input", nodeType: "input", description: "Game state observation and frame encoding", matchReasons: [], matchFilePatterns: ["game", "state", "frame", "env"], matchSkillLabels: [] },
      { id: "cnn", label: "CNN / Model Logic", nodeType: "compute", description: "Neural network model for action prediction", matchReasons: ["ML model instantiation", "ML training call"], matchFilePatterns: ["model.py", "cnn", "network", "agent", "fight"], matchSkillLabels: ["Machine Learning"] },
      { id: "logits", label: "Action Logits", nodeType: "output", description: "Raw action probability output from the model", matchReasons: ["ML prediction/inference"], matchFilePatterns: ["predict", "action", "logit"], matchSkillLabels: [] },
      { id: "selection", label: "Action Selection", nodeType: "decision", description: "Policy-based selection of game action", matchReasons: [], matchFilePatterns: ["policy", "select", "agent"], matchSkillLabels: [] },
      { id: "execution", label: "FightingICE Execution", nodeType: "environment", description: "Game environment execution and evaluation", matchReasons: [], matchFilePatterns: ["fighting", "ice", "main", "eval"], matchSkillLabels: [] },
    ],
  },
  "DevOps / CI-CD": {
    title: "DevOps / CI-CD System Graph",
    summary: "Automated deployment: workflow → build → container → deploy → health check.",
    nodes: [
      { id: "workflow", label: "GitHub Actions Workflow", nodeType: "automation", description: "CI/CD pipeline definition", matchReasons: ["CI/CD workflow step"], matchFilePatterns: [".github/workflows", "workflow"], matchSkillLabels: ["CI/CD"] },
      { id: "docker", label: "Container Build", nodeType: "build", description: "Docker image build and push", matchReasons: ["Dockerfile instruction"], matchFilePatterns: ["dockerfile"], matchSkillLabels: ["Docker"] },
      { id: "deploy", label: "Deploy", nodeType: "deployment", description: "Automated deployment to target environment", matchReasons: ["Cloud deployment command"], matchFilePatterns: ["deploy", "cloud-run"], matchSkillLabels: [] },
      { id: "health", label: "Health Check", nodeType: "validation", description: "Post-deployment service verification", matchReasons: [], matchFilePatterns: ["health", "ping", "status"], matchSkillLabels: [] },
    ],
  },
  "Data Engineering": {
    title: "Data Engineering System Graph",
    summary: "Data pipeline: ingestion → cleaning → feature engineering → processed output.",
    nodes: [
      { id: "ingest", label: "Data Ingestion", nodeType: "input", description: "Raw data loading from files or APIs", matchReasons: ["Data preprocessing"], matchFilePatterns: ["data", ".csv", "ingest", "load", "read_csv"], matchSkillLabels: ["Data Engineering"] },
      { id: "clean", label: "Data Cleaning", nodeType: "transform", description: "Missing value handling and normalization", matchReasons: ["Data preprocessing"], matchFilePatterns: ["clean", "preprocess", "fillna", "dropna"], matchSkillLabels: [] },
      { id: "transform", label: "Feature Engineering", nodeType: "transform", description: "Feature extraction and transformation", matchReasons: ["Data preprocessing"], matchFilePatterns: ["feature", "transform", "pipeline", "encoder"], matchSkillLabels: [] },
      { id: "output", label: "Processed Dataset", nodeType: "output", description: "Export or store processed data", matchReasons: [], matchFilePatterns: ["export", "output", "save", "to_csv"], matchSkillLabels: [] },
    ],
  },
}

function matchNodeEvidence(template: GraphNodeTemplate, items: SkillEvidence[]): SkillEvidence[] {
  return items.filter((e) => {
    const fileLower = e.filePath.toLowerCase()
    const reasonMatch = template.matchReasons.includes(e.selectionReason)
    const fileMatch =
      template.matchFilePatterns.length > 0 &&
      template.matchFilePatterns.some((p) => fileLower.includes(p.toLowerCase()))
    const skillMatch = template.matchSkillLabels.includes(e.skillLabel)
    return reasonMatch || fileMatch || skillMatch
  })
}

export function buildSkillSystemGraph(grouped: GroupedSkillSuggestion): SkillSystemGraph | null {
  const template = GRAPH_TEMPLATES[grouped.skillName]
  if (!template || grouped.evidenceItems.length === 0) return null

  const nodes: SkillGraphNode[] = template.nodes.map((t) => {
    const matched = matchNodeEvidence(t, grouped.evidenceItems)
    const conf: ConfidenceLevel = matched.length >= 2 ? "high" : matched.length === 1 ? "medium" : "low"
    return {
      id: t.id,
      label: t.label,
      nodeType: t.nodeType,
      evidenceCount: matched.length,
      confidence: conf,
      evidenceItemIds: matched.map((e) => e.candidateId),
      description: t.description,
      hasEvidence: matched.length > 0,
    }
  })

  const edges: SkillGraphEdge[] = nodes.slice(0, -1).map((node, i) => ({
    id: `edge-${node.id}-to-${nodes[i + 1].id}`,
    from: node.id,
    to: nodes[i + 1].id,
    relationshipLabel: "→",
  }))

  const supportedCount = nodes.filter((n) => n.hasEvidence).length
  const graphConf: ConfidenceLevel = supportedCount >= 3 ? "high" : supportedCount >= 1 ? "medium" : "low"

  return {
    id: `graph-${grouped.id}`,
    skillId: grouped.id,
    title: template.title,
    summary: template.summary,
    nodes,
    edges,
    confidence: graphConf,
    needsReview: supportedCount < 2,
  }
}

// ── Main grouping function ────────────────────────────────────────────────────

export function groupProofSuggestions(candidates: GitHubPortfolioScanCandidate[]): GroupedSkillSuggestion[] {
  // Convert each candidate to SkillEvidence + resolve its parent category
  const categorized = candidates.map((c) => ({
    evidence: {
      candidateId: c.candidate_id,
      repoName: c.repo_name,
      repoUrl: c.repo_url,
      projectTitle: c.project_title,
      filePath: c.file_path,
      lineStart: c.line_start,
      lineEnd: c.line_end,
      githubHighlightUrl: c.github_highlight_url,
      selectionReason: c.selection_reason,
      evidenceDescription: c.evidence_description,
      confidence: c.confidence_label,
      suggestedStatus: c.suggested_status,
      evidenceType: inferEvidenceType(c.file_path, c.selection_reason),
      skillLabel: c.skill_label,
      evidenceSource: "github",
    } as SkillEvidence,
    parentCategory: resolveParentCategory(c),
  }))

  // Group by parent category
  const groupMap = new Map<string, SkillEvidence[]>()
  for (const { evidence, parentCategory } of categorized) {
    const existing = groupMap.get(parentCategory) ?? []
    existing.push(evidence)
    groupMap.set(parentCategory, existing)
  }

  const result: GroupedSkillSuggestion[] = []

  for (const [skillName, evidenceItems] of groupMap.entries()) {
    const id = normalizeSkillName(skillName)
    const repos = [...new Set(evidenceItems.map((e) => e.repoName))]

    // Subskill aggregation
    const subskillMap = new Map<string, number>()
    for (const e of evidenceItems) {
      const name = getSubskillName(e.skillLabel, e.selectionReason)
      subskillMap.set(name, (subskillMap.get(name) ?? 0) + 1)
    }
    const subskills: SkillSubskill[] = [...subskillMap.entries()]
      .map(([name, evidenceCount]) => ({ name, evidenceCount }))
      .sort((a, b) => b.evidenceCount - a.evidenceCount)

    // Project groups (by repo)
    const projectMap = new Map<string, ProjectEvidenceGroup>()
    for (const e of evidenceItems) {
      const existing = projectMap.get(e.repoName) ?? {
        repoName: e.repoName,
        repoUrl: e.repoUrl,
        projectTitle: e.projectTitle,
        evidenceItems: [],
      }
      existing.evidenceItems.push(e)
      projectMap.set(e.repoName, existing)
    }

    const confidence = calculateSkillConfidence(evidenceItems)
    const repoCount = repos.length

    const grouped: GroupedSkillSuggestion = {
      id,
      skillName,
      normalizedSkillName: id,
      category: mapSkillToCategory(skillName),
      parentSkill: null,
      confidence,
      statusSummary: `${evidenceItems.length} evidence location${evidenceItems.length === 1 ? "" : "s"} across ${repoCount} repo${repoCount === 1 ? "" : "s"}`,
      evidenceCount: evidenceItems.length,
      repoCount,
      repositories: repos,
      subskills,
      evidenceItems,
      projectGroups: [...projectMap.values()],
      systemGraph: null,
    }

    // Build system graph (references the grouped object, so done last)
    grouped.systemGraph = buildSkillSystemGraph(grouped)

    result.push(grouped)
  }

  // Sort: highest evidence count first
  result.sort((a, b) => b.evidenceCount - a.evidenceCount)

  return result
}

// ── Utility exports ───────────────────────────────────────────────────────────

/** Returns the set of candidateIds that belong to selected groups. */
export function getCandidateIdsForGroups(
  groups: GroupedSkillSuggestion[],
  groupIds: Set<string>
): Set<string> {
  const ids = new Set<string>()
  for (const g of groups) {
    if (groupIds.has(g.id)) {
      for (const e of g.evidenceItems) ids.add(e.candidateId)
    }
  }
  return ids
}

/** True if every evidence item in the group is in `selectedCandidateIds`. */
export function isGroupFullySelected(group: GroupedSkillSuggestion, selectedCandidateIds: Set<string>): boolean {
  return group.evidenceItems.length > 0 && group.evidenceItems.every((e) => selectedCandidateIds.has(e.candidateId))
}

/** True if at least one (but not all) evidence items are selected. */
export function isGroupPartiallySelected(group: GroupedSkillSuggestion, selectedCandidateIds: Set<string>): boolean {
  const someSelected = group.evidenceItems.some((e) => selectedCandidateIds.has(e.candidateId))
  return someSelected && !isGroupFullySelected(group, selectedCandidateIds)
}

// ── J4A: Saved evidence utilities ─────────────────────────────────────────────

/** Maps an evidence_type string to a canonical EvidenceSource. */
export function mapEvidenceSourceType(evidenceType: string): EvidenceSource {
  const t = evidenceType.toLowerCase().trim()
  if (t === "github repository") return "github"
  if (t === "deployed website") return "website"
  if (t === "linkedin_post") return "linkedin"
  if (t === "certificate") return "certificate"
  if (t === "youtube_demo") return "youtube"
  if (t === "pdf_report") return "pdf"
  if (t === "portfolio" || t === "portfolio_url") return "portfolio"
  if (t === "google_drive_document" || t === "google_drive") return "google_drive"
  if (t === "manual_entry" || t === "manual" || t === "resume_bullet") return "manual"
  if (t === "other_link") return "other"
  return "other"
}

/** Human-readable label for a source type, used in badges. */
export function getEvidenceSourceLabel(evidenceType: string): string {
  const labels: Record<EvidenceSource, string> = {
    github: "GitHub",
    website: "Website",
    linkedin: "LinkedIn",
    certificate: "Certificate",
    youtube: "YouTube",
    pdf: "Document",
    portfolio: "Portfolio",
    manual: "Manual",
    google_drive: "Google Drive",
    other: "Other",
  }
  return labels[mapEvidenceSourceType(evidenceType)] ?? "Other"
}

/**
 * CTA label for the redirect link on an evidence item.
 * Pass displayMetadata to get YouTube timestamp in the label.
 */
export function getEvidenceActionLabel(
  evidenceType: string,
  displayMetadata?: Record<string, unknown>
): string {
  const source = mapEvidenceSourceType(evidenceType)
  if (source === "youtube") {
    const ts = displayMetadata?.timestamp_start_formatted
    return typeof ts === "string" ? `Open Demo Video at ${ts}` : "Open Demo Video"
  }
  const labels: Record<EvidenceSource, string> = {
    github: "Open GitHub Evidence",
    website: "Open Live Website",
    linkedin: "Open LinkedIn Post",
    certificate: "Verify Certificate",
    youtube: "Open Demo Video",
    pdf: "Open Document",
    portfolio: "Open Portfolio",
    manual: "View Proof Details",
    google_drive: "Open Drive Document",
    other: "Open Resource",
  }
  return labels[source] ?? "View Evidence"
}

/** Returns the best redirect URL for a saved evidence item, or null if none. */
export function getEvidenceRedirectUrl(evidence: SkillEvidenceResponse): string | null {
  const metadata = (evidence.metadata as Record<string, unknown> | undefined) ?? {}

  if (evidence.evidence_type === "github repository") {
    // Prefer the pre-built highlight URL stored in metadata
    if (typeof metadata.github_highlight_url === "string" && metadata.github_highlight_url) {
      return metadata.github_highlight_url
    }
    // Fall back to building a URL from repo + file + lines
    if (evidence.repository_url) {
      const base = evidence.repository_url.replace(/\/$/, "")
      if (evidence.file_path) {
        const branch = typeof metadata.branch_ref === "string" && metadata.branch_ref ? metadata.branch_ref : "main"
        const anchor = evidence.line_start ? `#L${evidence.line_start}${evidence.line_end ? `-L${evidence.line_end}` : ""}` : ""
        return `${base}/blob/${branch}/${evidence.file_path}${anchor}`
      }
      return base
    }
  }

  // All other types: use evidence_url
  return evidence.evidence_url ?? null
}

// ── Internal helpers for groupSavedEvidence ───────────────────────────────────

function extractRepoNameFromUrl(url: string): string {
  try {
    const u = new URL(url)
    const parts = u.pathname.split("/").filter(Boolean)
    if (u.hostname.includes("github.com") && parts.length >= 2) return parts[1]
    return parts[parts.length - 1] ?? u.hostname
  } catch {
    return url.split("/").filter(Boolean).pop() ?? "project"
  }
}

function verificationStatusToConfidence(status: string): ConfidenceLevel {
  if (status === "verified") return "high"
  if (status === "pending_review" || status === "needs_review") return "medium"
  return "low"
}

// Maps evidence_type to a plausible detection reason for grouping when metadata.selection_reason is absent
const EVIDENCE_TYPE_TO_DEFAULT_REASON: Record<string, string> = {
  "github repository": "code line",
  "deployed website": "live website demo",
  "linkedin_post": "linkedin post",
  "certificate": "certificate credential",
  "youtube_demo": "demo video",
  "pdf_report": "document proof",
  "google_drive_document": "document proof",
  "portfolio": "portfolio link",
  "portfolio_url": "portfolio link",
  "other_link": "external link",
  "manual_entry": "manual entry",
  "manual": "manual entry",
  "resume_bullet": "resume bullet",
}

function resolveSavedEvidenceParent(e: SkillEvidenceResponse): string {
  const skillName = e.skill_name
  const metadata = (e.metadata as Record<string, unknown> | undefined) ?? {}
  const storedReason = typeof metadata.selection_reason === "string" ? metadata.selection_reason : ""
  const filePath = e.file_path ?? ""

  // 1. Direct skill label mapping (unambiguous, e.g. "Docker" → "MLOps")
  const direct = SKILL_LABEL_TO_PARENT[skillName]
  if (direct) return direct

  // 2. Use the stored detection reason from the scan metadata (GitHub scan imports)
  if (storedReason) {
    const fromReason = DETECTION_REASON_TO_PARENT[storedReason]
    if (fromReason) return fromReason
  }

  // 3. File path inference (manual GitHub submissions)
  if (filePath) {
    const fromPath = inferParentFromFilePath(filePath)
    if (fromPath) return fromPath
  }

  // 4. Fall back to skill_name (keeps non-IT skills intact)
  return skillName
}

/** Groups saved SkillEvidenceResponse[] into hierarchical skill categories (J4A). */
export function groupSavedEvidence(evidence: SkillEvidenceResponse[]): GroupedSkillSuggestion[] {
  if (evidence.length === 0) return []

  const categorized = evidence.map((e) => {
    const metadata = (e.metadata as Record<string, unknown> | undefined) ?? {}

    const githubHighlightUrl =
      typeof metadata.github_highlight_url === "string" && metadata.github_highlight_url
        ? metadata.github_highlight_url
        : (e.repository_url ?? e.evidence_url ?? "")

    const selectionReason =
      typeof metadata.selection_reason === "string" && metadata.selection_reason
        ? metadata.selection_reason
        : (EVIDENCE_TYPE_TO_DEFAULT_REASON[e.evidence_type] ?? e.evidence_type)

    const projectTitle =
      typeof metadata.evidence_title === "string" && metadata.evidence_title.trim()
        ? metadata.evidence_title.trim()
        : e.skill_name

    const repoUrl = e.repository_url ?? e.evidence_url ?? ""
    const repoName = repoUrl ? extractRepoNameFromUrl(repoUrl) : e.skill_name

    const ev: SkillEvidence = {
      candidateId: e.id,
      repoName,
      repoUrl,
      projectTitle,
      filePath: e.file_path ?? "",
      lineStart: e.line_start ?? 1,
      lineEnd: e.line_end ?? 1,
      githubHighlightUrl,
      selectionReason,
      evidenceDescription: e.evidence_description ?? "",
      confidence: verificationStatusToConfidence(e.verification_status),
      suggestedStatus: e.verification_status,
      evidenceType: inferEvidenceType(e.file_path ?? "", selectionReason),
      skillLabel: e.skill_name,
      evidenceSource: mapEvidenceSourceType(e.evidence_type),
      displayMetadata: typeof metadata === "object" && metadata !== null ? metadata : undefined,
    }
    return { evidence: ev, parentCategory: resolveSavedEvidenceParent(e) }
  })

  // Group by parent category
  const groupMap = new Map<string, SkillEvidence[]>()
  for (const { evidence: ev, parentCategory } of categorized) {
    const existing = groupMap.get(parentCategory) ?? []
    existing.push(ev)
    groupMap.set(parentCategory, existing)
  }

  const result: GroupedSkillSuggestion[] = []

  for (const [skillName, evidenceItems] of groupMap.entries()) {
    const id = normalizeSkillName(skillName)
    const repos = [...new Set(evidenceItems.map((e) => e.repoName))]

    // Subskills
    const subskillMap = new Map<string, number>()
    for (const e of evidenceItems) {
      const name =
        !["Python", "JavaScript", "TypeScript"].includes(e.skillLabel)
          ? e.skillLabel
          : (REASON_TO_SUBSKILL[e.selectionReason] ?? e.skillLabel)
      subskillMap.set(name, (subskillMap.get(name) ?? 0) + 1)
    }
    const subskills: SkillSubskill[] = [...subskillMap.entries()]
      .map(([name, evidenceCount]) => ({ name, evidenceCount }))
      .sort((a, b) => b.evidenceCount - a.evidenceCount)

    // Project groups (keyed by repoName, or skill+source for non-GitHub)
    const projectMap = new Map<string, ProjectEvidenceGroup>()
    for (const e of evidenceItems) {
      const key = e.repoName || e.skillLabel
      const existing = projectMap.get(key) ?? {
        repoName: e.repoName,
        repoUrl: e.repoUrl,
        projectTitle: e.projectTitle,
        evidenceItems: [],
      }
      existing.evidenceItems.push(e)
      projectMap.set(key, existing)
    }

    const confidence = calculateSkillConfidence(evidenceItems)
    const repoCount = repos.length

    const grouped: GroupedSkillSuggestion = {
      id,
      skillName,
      normalizedSkillName: id,
      category: mapSkillToCategory(skillName),
      parentSkill: null,
      confidence,
      statusSummary: `${evidenceItems.length} saved item${evidenceItems.length === 1 ? "" : "s"} across ${repoCount} source${repoCount === 1 ? "" : "s"}`,
      evidenceCount: evidenceItems.length,
      repoCount,
      repositories: repos,
      subskills,
      evidenceItems,
      projectGroups: [...projectMap.values()],
      systemGraph: null,
    }
    grouped.systemGraph = buildSkillSystemGraph(grouped)
    result.push(grouped)
  }

  result.sort((a, b) => b.evidenceCount - a.evidenceCount)
  return result
}
