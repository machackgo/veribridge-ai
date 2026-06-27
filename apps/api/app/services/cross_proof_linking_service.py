"""Cross-Proof Linking Engine (Step 3) — connect related evidence into chains.

Step 2's :mod:`evidence_normalization_service` collapsed every proof surface into
ONE uniform internal shape (:class:`NormalizedEvidenceArtifact`). This module is
the next layer: it reads that uniform set and *links* artifacts that describe the
**same** project, repository, endpoint, model, feature, file or explanation into a
connected :class:`LinkedProofChain`. The goal is that Step 4's (later) LLM
synthesis can cite a ready-made, deterministic proof chain instead of re-deriving
"which evidence goes together" itself.

It is **purely deterministic** — never an LLM, never a source-table read. Two
artifacts link only when they share a concrete, deterministic signal:

* the same VBR ``project_id`` (project attachment — the strongest signal),
* the same normalized, *distinctive* ``project_title``,
* the same repository (``owner/name`` parsed from a GitHub URL), or
* a shared **structural identifier** — an endpoint path (``/predict``), a function
  name, a file/located token — that is structural for at least one side and is
  carried by the other (e.g. GitHub locates ``predict()`` and a Project Defense
  answer explains the ``/predict`` endpoint), within the same canonical skill.

False-positive prevention (every rule below is deterministic):

* The same *generic skill* appearing in two unrelated projects never merges them —
  a skill word alone is excluded from the linking tokens.
* Broad generic words (``app``, ``page``, ``model``, ``data``, ``project``,
  ``code``, ``api`` …) are blocklisted, so coincidental prose overlap can't link.
* A token only links when it is **structural** for at least one side (an endpoint /
  function / file / located identifier), so two free-text summaries that merely
  mention the same common word never link on that basis alone.
* An explicit, **conflicting ``project_id`` is a hard blocker** at the *connected-
  component* level — two artifacts that each name a *different* project never merge,
  whether on a single shared structural token (both exposing ``/predict`` in
  ``project-a`` vs ``project-b`` stays two chains) or transitively through several
  token buckets. A ``project_id``-less artifact can never *bridge* two conflicting
  projects: if it is compatible with more than one explicit project it is dropped
  from that linking layer entirely — from structural linking when it shares
  structural tokens with several projects, and from Layer-1 project-signal linking
  when it shares a title / repo with several projects (so it never attaches to one
  side by input order). It may still attach when only **one** explicit project is
  reachable. The guard fires component-wide, not just inside one bucket.
* **Documents corroborate only.** A document joins a chain solely through a shared
  project signal (never through a free-text token), and is never selected as the
  chain's ``primary_source_type``.

Product rules preserved from Step 2:

* GitHub precise, line-level code is the preferred ``primary_source_type``;
  repository-level GitHub is a weaker fallback and never overrides precise code.
* Website runtime, Project Defense and Video evidence corroborate/explain but never
  override code as the primary implementation proof.

Safety: a :class:`LinkedProofChain` only ever holds already-safe fields plus the
safe ``ev_…`` evidence-id hashes (so Step 4 can cite them). The public-safe
projection (:meth:`LinkedProofChain.public_view`) drops the private
``project_id``, drops each member's private ``source_id`` / internal metadata (via
the artifact's own :meth:`~NormalizedEvidenceArtifact.public_view`), and
re-scrubs every retained string with the same canonical sensitive-data scrubber
Step 2 uses — so no raw transcript / document text / DOM / provider JSON / storage
path / signed URL / private id / email / raw payload can leak.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.services.evidence_normalization_service import (
    SOURCE_DEFENSE,
    SOURCE_DOCUMENT,
    SOURCE_GITHUB,
    SOURCE_SKILL_GRAPH,
    SOURCE_VIDEO,
    SOURCE_WEBSITE,
    STRENGTH_AGGREGATED,
    STRENGTH_CORROBORATION,
    STRENGTH_PRECISE_CODE,
    STRENGTH_REPO_LEVEL,
    STRENGTH_RUNTIME,
    STRENGTH_SELF_EXPLANATION,
    STRENGTH_SUPPORTING_MOMENT,
    NormalizedEvidenceArtifact,
    _scrub_sensitive,
    normalize_skill_report,
)

__all__ = [
    "LinkedProofChain",
    "link_proof_chains",
    "link_skill_report",
]

# ── Source ordering / ranking ─────────────────────────────────────────────────
# Strong-first display order for ``source_types_present`` (documents last — they
# only corroborate).
_SOURCE_DISPLAY_ORDER = (
    SOURCE_GITHUB,
    SOURCE_WEBSITE,
    SOURCE_DEFENSE,
    SOURCE_VIDEO,
    SOURCE_SKILL_GRAPH,
    SOURCE_DOCUMENT,
)

# Strongest → weakest, used to order members and pick the primary source type.
# Precise GitHub code outranks everything; documents are last and are never primary.
_STRENGTH_RANK = {
    STRENGTH_PRECISE_CODE: 0,
    STRENGTH_RUNTIME: 1,
    STRENGTH_REPO_LEVEL: 2,
    STRENGTH_SELF_EXPLANATION: 3,
    STRENGTH_SUPPORTING_MOMENT: 4,
    STRENGTH_AGGREGATED: 5,
    STRENGTH_CORROBORATION: 6,
}

# Generic words that must NEVER, on their own, link two artifacts. Mirrors the
# product rule: "Avoid broad false-positive links from generic words like app,
# page, model, data, project, code, API alone." Kept lower-cased.
_GENERIC_TOKENS = frozenset(
    {
        "app",
        "apps",
        "page",
        "pages",
        "model",
        "models",
        "data",
        "dataset",
        "project",
        "projects",
        "code",
        "codebase",
        "api",
        "apis",
        "rest",
        "endpoint",
        "endpoints",
        "route",
        "routes",
        "router",
        "request",
        "requests",
        "response",
        "responses",
        "handler",
        "handlers",
        "function",
        "functions",
        "method",
        "methods",
        "class",
        "classes",
        "module",
        "modules",
        "file",
        "files",
        "folder",
        "main",
        "index",
        "util",
        "utils",
        "helper",
        "helpers",
        "test",
        "tests",
        "build",
        "builds",
        "run",
        "runs",
        "runtime",
        "deploy",
        "deployed",
        "deployment",
        "service",
        "services",
        "server",
        "client",
        "user",
        "users",
        "view",
        "views",
        "component",
        "components",
        "feature",
        "features",
        "system",
        "systems",
        "application",
        "applications",
        "website",
        "site",
        "online",
        "live",
        "demo",
        "sample",
        "example",
        "examples",
        "repository",
        "repo",
        "github",
        "document",
        "documents",
        "defense",
        "video",
        "evidence",
        "skill",
        "skills",
        "proof",
        "proofs",
        "candidate",
        "explained",
        "explains",
        "explain",
        "shows",
        "show",
        "support",
        "supports",
        "supporting",
        "implementation",
        "implements",
        "behavior",
        "behaviour",
        "work",
        "works",
        "working",
        "workflow",
        "workflows",
        "overall",
        "general",
        "various",
        "multiple",
        "simple",
        "basic",
        "dashboard",
        "frontend",
        "backend",
        "database",
        "https",
        "http",
        "www",
        "com",
        "blob",
        "tree",
        "page2",
    }
)

# Word token: a letter then 3+ alphanumerics → total length >= 4 (so "api", "ml",
# "id" never become link tokens; "predict", "rerouting" do).
_WORD_RE = re.compile(r"[a-z][a-z0-9]{3,}")
# Endpoint/path segment, e.g. "/predict" or "/v1/forecast" → captures "predict".
_PATH_SEGMENT_RE = re.compile(r"/([a-zA-Z][\w-]{2,})")
# Skill-name token (shorter min length so "api"/"ml" are excluded as link tokens).
_SKILL_WORD_RE = re.compile(r"[a-z][a-z0-9]{1,}")


# ── The linked chain model ────────────────────────────────────────────────────


@dataclass(frozen=True)
class LinkedProofChain:
    """A connected group of normalized artifacts that describe the same work.

    Holds ONLY safe fields plus the safe ``ev_…`` evidence-id hashes (so Step 4
    can cite the exact evidence). :meth:`public_view` drops the private
    ``project_id`` and every member's private ``source_id`` / internal metadata,
    and re-scrubs the retained strings.
    """

    chain_id: str
    project_id: str | None
    project_title: str | None
    skill_name: str | None
    canonical_skill_name: str | None
    chain_label: str
    linked_evidence_ids: tuple[str, ...]
    source_types_present: tuple[str, ...]
    primary_source_type: str | None
    connection_reasons: tuple[str, ...]
    proof_strength_summary: dict[str, Any]
    limitations: tuple[str, ...]
    public_safe: bool
    artifacts: tuple[NormalizedEvidenceArtifact, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Full INTERNAL representation (keeps ``project_id`` + member internals)."""
        return {
            "chain_id": self.chain_id,
            "project_id": self.project_id,
            "project_title": self.project_title,
            "skill_name": self.skill_name,
            "canonical_skill_name": self.canonical_skill_name,
            "chain_label": self.chain_label,
            "linked_evidence_ids": list(self.linked_evidence_ids),
            "source_types_present": list(self.source_types_present),
            "primary_source_type": self.primary_source_type,
            "connection_reasons": list(self.connection_reasons),
            "proof_strength_summary": dict(self.proof_strength_summary),
            "limitations": list(self.limitations),
            "public_safe": self.public_safe,
            "evidence": [a.to_dict() for a in self.artifacts],
        }

    def public_view(self) -> dict[str, Any]:
        """PUBLIC-SAFE projection — no private project_id / source_id / metadata.

        Drops the private ``project_id``; every member is projected through its own
        :meth:`~NormalizedEvidenceArtifact.public_view` (which strips ``source_id``
        and the internal ``metadata`` bag and re-scrubs its strings); and every
        retained chain string is re-scrubbed with the canonical sensitive-data
        scrubber. The safe ``linked_evidence_ids`` (``ev_…`` hashes) survive so a
        downstream consumer can still cite the exact evidence.
        """
        return {
            "chain_id": self.chain_id,
            "project_title": _scrub_sensitive(self.project_title),
            "canonical_skill_name": self.canonical_skill_name,
            "chain_label": _scrub_sensitive(self.chain_label) or "",
            "linked_evidence_ids": list(self.linked_evidence_ids),
            "source_types_present": list(self.source_types_present),
            "primary_source_type": self.primary_source_type,
            "connection_reasons": [_scrub_sensitive(r) for r in self.connection_reasons],
            "proof_strength_summary": dict(self.proof_strength_summary),
            "limitations": [_scrub_sensitive(limit) for limit in self.limitations],
            "public_safe": self.public_safe,
            "evidence": [a.public_view() for a in self.artifacts],
        }


# ── Union-find (deterministic connected components) ───────────────────────────


class _UnionFind:
    """Tiny union-find so transitive links (A↔B, B↔C ⇒ A,B,C one chain) collapse."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, i: int) -> int:
        root = i
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[i] != root:
            self._parent[i], i = root, self._parent[i]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Lower index wins → deterministic, order-independent roots.
            self._parent[max(ra, rb)] = min(ra, rb)


# ── Signal extraction ─────────────────────────────────────────────────────────


def _norm_title(title: str | None) -> str:
    return re.sub(r"[\s_\-/]+", " ", str(title or "").strip().lower())


def _title_signal(title: str | None) -> str | None:
    """A project title is a link signal only when it is distinctive.

    A short or wholly-generic title (``app``, ``demo``) must not link two
    artifacts, so we require >= 6 chars and at least one non-generic word token.
    """
    norm = _norm_title(title)
    if len(norm) < 6:
        return None
    if any(w not in _GENERIC_TOKENS for w in _WORD_RE.findall(norm)):
        return norm
    return None


def _repo_identity(*urls: Any) -> str | None:
    """Parse ``owner/name`` (lower-cased, no ``.git``) from a GitHub URL."""
    for url in urls:
        match = re.search(r"github\.com[:/]+([^/\s]+/[^/\s#?]+)", str(url or ""), re.IGNORECASE)
        if match:
            return match.group(1).lower().removesuffix(".git")
    return None


def _project_signals(artifact: NormalizedEvidenceArtifact) -> list[tuple[str, str]]:
    """Strong project-level link signals (carried by ALL source types, incl. docs)."""
    signals: list[tuple[str, str]] = []
    if artifact.project_id:
        signals.append(("project_id", str(artifact.project_id)))
    title = _title_signal(artifact.project_title)
    if title:
        signals.append(("project_title", title))
    repo = _repo_identity(artifact.metadata.get("repo_url"), artifact.metadata.get("github_line_url"))
    if repo:
        signals.append(("repo", repo))
    return signals


def _structural_blobs(artifact: NormalizedEvidenceArtifact) -> list[str]:
    """Text whose tokens identify a *located* thing (endpoint/function/file).

    Deliberately excludes ``repo_url`` / ``github_line_url``: the repository
    identity is already a project-level signal (:func:`_repo_identity`), and
    word-tokenizing the URL would leak the repo *owner* / host (e.g. ``octocat``)
    as a spurious structural token that could falsely link two different repos
    owned by the same account.
    """
    meta = artifact.metadata
    blobs = [artifact.exact_location or ""]
    for key in ("function_name", "file_path", "timestamp_label", "section_label", "citation"):
        if meta.get(key):
            blobs.append(str(meta[key]))
    return blobs


def _mention_blobs(artifact: NormalizedEvidenceArtifact) -> list[str]:
    """Free-text whose tokens are only *mentions* (never structural on their own)."""
    meta = artifact.metadata
    blobs = [artifact.safe_summary or ""]
    for key in ("selection_reason", "question_text", "corroborates", "workflow_summary"):
        if meta.get(key):
            blobs.append(str(meta[key]))
    return blobs


def _filter_tokens(tokens: set[str], skill_tokens: frozenset[str]) -> set[str]:
    """Drop generic words, skill-name words, numerics and too-short tokens."""
    out: set[str] = set()
    for raw in tokens:
        tok = raw.strip("_-").lower()
        if len(tok) < 4 or tok.isdigit():
            continue
        if tok in _GENERIC_TOKENS or tok in skill_tokens:
            continue
        out.add(tok)
    return out


def _structural_tokens(
    artifact: NormalizedEvidenceArtifact, skill_tokens: frozenset[str]
) -> set[str]:
    """Specific identifiers structural for this artifact (endpoint/function/file).

    An endpoint path (``/predict``) is treated as structural wherever it appears —
    a Project Defense answer that names ``/predict`` is asserting a concrete API,
    not coincidental prose — as is an explicit ``function_name`` and any token from
    a structural blob (file path, located line label, public URL).
    """
    tokens: set[str] = set()
    for blob in _structural_blobs(artifact):
        tokens |= set(_WORD_RE.findall(blob.lower()))
    # Endpoint/path segments anywhere (explicit API/route reference).
    all_text = " ".join(_structural_blobs(artifact) + _mention_blobs(artifact))
    for seg in _PATH_SEGMENT_RE.findall(all_text):
        tokens.add(seg.lower())
    fn = artifact.metadata.get("function_name")
    if fn:
        tokens.add(str(fn).lower())
    return _filter_tokens(tokens, skill_tokens)


def _mention_tokens(
    artifact: NormalizedEvidenceArtifact, skill_tokens: frozenset[str]
) -> set[str]:
    """All specific tokens this artifact carries (structural + free-text mentions)."""
    tokens: set[str] = set(_structural_tokens(artifact, skill_tokens))
    for blob in _mention_blobs(artifact):
        tokens |= set(_WORD_RE.findall(blob.lower()))
    return _filter_tokens(tokens, skill_tokens)


def _skill_tokens(artifacts: list[NormalizedEvidenceArtifact]) -> frozenset[str]:
    """Every word that is part of a skill name — excluded from link tokens.

    This is what stops "the same generic skill" from merging two unrelated
    projects: the skill word itself can never be the thing that links them.
    """
    tokens: set[str] = set()
    for artifact in artifacts:
        for name in (artifact.skill_name, artifact.canonical_skill_name):
            tokens |= set(_SKILL_WORD_RE.findall(str(name or "").lower()))
    return frozenset(tokens)


# ── Chain construction ────────────────────────────────────────────────────────


def _chain_id(evidence_ids: tuple[str, ...]) -> str:
    """Stable, non-leaking chain id — a hash of the sorted member evidence ids.

    Because each member ``evidence_id`` is itself a deterministic hash, the same
    set of evidence always yields the same ``chain_id`` (and the id never reveals
    a private source id).
    """
    raw = "␟".join(sorted(evidence_ids))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"chain_{digest}"


def _mode(values: list[Any]) -> Any | None:
    """Most common non-empty value (deterministic tie-break by string order)."""
    counts = Counter(v for v in values if v)
    if not counts:
        return None
    return sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0]


def _ordered_source_types(members: list[NormalizedEvidenceArtifact]) -> tuple[str, ...]:
    present = {m.source_type for m in members}
    return tuple(s for s in _SOURCE_DISPLAY_ORDER if s in present)


def _primary_source_type(members: list[NormalizedEvidenceArtifact]) -> str | None:
    """Pick the chain's primary implementation proof — NEVER a document.

    Precise GitHub code wins; then a Website runtime workflow; then repo-level
    GitHub; then Defense; then Video; then Skill Graph. Documents are excluded
    entirely (they corroborate, never prove), so a document-only chain has no
    primary source type.
    """
    ranked = sorted(
        (m for m in members if m.source_type != SOURCE_DOCUMENT),
        key=lambda m: (_STRENGTH_RANK.get(m.proof_strength, 9), m.evidence_id),
    )
    return ranked[0].source_type if ranked else None


def _connection_reasons(
    members: list[NormalizedEvidenceArtifact], skill_tokens: frozenset[str]
) -> tuple[str, ...]:
    """Deterministic, signal-referencing reasons these artifacts are one chain.

    Every reason names the concrete shared signal that linked the members — a
    shared project attachment, title, repository, or a structural identifier that
    at least two members carry (structural for at least one). Never LLM reasoning.
    """
    if len(members) < 2:
        return ("Single-source evidence — no cross-proof corroboration found yet.",)

    reasons: list[str] = []

    if sum(1 for m in members if m.project_id) >= 2 and _mode([m.project_id for m in members]):
        # Only a *shared* project id counts (>= 2 members carrying the same one).
        shared_pid = _mode([m.project_id for m in members])
        if sum(1 for m in members if m.project_id == shared_pid) >= 2:
            reasons.append("Same VBR project (shared project attachment).")

    title_counts = Counter(t for m in members if (t := _title_signal(m.project_title)))
    for norm_title, count in title_counts.most_common(1):
        if count >= 2:
            display = _mode([m.project_title for m in members if _title_signal(m.project_title) == norm_title])
            reasons.append(f"Same project title: “{display}”.")

    repo_counts = Counter(
        r
        for m in members
        if (r := _repo_identity(m.metadata.get("repo_url"), m.metadata.get("github_line_url")))
    )
    for repo, count in repo_counts.most_common(1):
        if count >= 2:
            reasons.append(f"Same repository: {repo}.")

    # Structural-token links: a token shared by >= 2 members and structural for
    # >= 1 of them (so coincidental prose overlap never produces a reason).
    structural_for: set[str] = set()
    carried_by: dict[str, set[int]] = defaultdict(set)
    for idx, member in enumerate(members):
        if member.source_type == SOURCE_DOCUMENT:
            continue  # documents corroborate; they never link by free-text token
        structural_for |= _structural_tokens(member, skill_tokens)
        for tok in _mention_tokens(member, skill_tokens):
            carried_by[tok].add(idx)
    shared_struct = sorted(
        tok for tok, idxs in carried_by.items() if tok in structural_for and len(idxs) >= 2
    )
    for tok in shared_struct[:4]:
        reasons.append(f"Shared code/endpoint identifier: “{tok}”.")

    return tuple(reasons) or (
        "Connected through shared deterministic evidence signals.",
    )


def _strength_summary(members: list[NormalizedEvidenceArtifact]) -> dict[str, Any]:
    """Qualitative (never numeric) summary of the chain's proof strengths."""
    strengths = {m.proof_strength for m in members}
    has_precise = STRENGTH_PRECISE_CODE in strengths
    has_runtime = STRENGTH_RUNTIME in strengths
    has_defense = STRENGTH_SELF_EXPLANATION in strengths
    has_video = STRENGTH_SUPPORTING_MOMENT in strengths
    has_repo_level = STRENGTH_REPO_LEVEL in strengths
    doc_count = sum(1 for m in members if m.source_type == SOURCE_DOCUMENT)

    if has_precise:
        label = "Implementation proven by precise code"
    elif has_runtime:
        label = "Runtime behaviour demonstrated"
    elif has_defense or has_video:
        label = "Explained by the candidate"
    elif has_repo_level:
        label = "Repository-level evidence only"
    elif STRENGTH_AGGREGATED in strengths:
        label = "Aggregated skill-graph evidence only"
    elif doc_count:
        label = "Corroborating evidence only"
    else:
        label = "Insufficient evidence"

    return {
        "label": label,
        "strengths_present": sorted(strengths),
        "has_precise_code": has_precise,
        "has_runtime_behavior": has_runtime,
        "has_self_explanation": has_defense,
        "has_supporting_moment": has_video,
        "repo_level_only": has_repo_level and not has_precise,
        "corroborating_document_count": doc_count,
    }


def _chain_limitations(members: list[NormalizedEvidenceArtifact]) -> tuple[str, ...]:
    """De-duped artifact limitations + structural caveats about proof strength."""
    out: list[str] = []

    def _add(text: str) -> None:
        text = str(text or "").strip()
        if text and text not in out:
            out.append(text)

    strengths = {m.proof_strength for m in members}
    has_anchor = any(m.source_type != SOURCE_DOCUMENT for m in members)
    if STRENGTH_PRECISE_CODE not in strengths and STRENGTH_REPO_LEVEL in strengths:
        _add("GitHub evidence is repository-level only — no precise code line was located.")
    if not has_anchor:
        _add("Only corroborating evidence — no primary implementation proof in this chain.")
    if any(m.source_type == SOURCE_DOCUMENT for m in members):
        _add("Documents corroborate only and are never counted as primary implementation proof.")

    for member in members:
        for limitation in member.limitations:
            _add(limitation)
    return tuple(out)


def _chain_label(skill: str | None, project_title: str | None) -> str:
    skill_part = skill or "this skill"
    title_part = project_title or "unattached evidence"
    return f"{skill_part} — {title_part}"


def _build_chain(
    members: list[NormalizedEvidenceArtifact], skill_tokens: frozenset[str]
) -> LinkedProofChain:
    members = sorted(
        members, key=lambda m: (_STRENGTH_RANK.get(m.proof_strength, 9), m.evidence_id)
    )
    evidence_ids = tuple(sorted(m.evidence_id for m in members))
    canonical = _mode([m.canonical_skill_name for m in members])
    skill_name = _mode([m.skill_name for m in members])
    project_title = _mode([m.project_title for m in members])
    public_safe = any(
        m.public_safe for m in members if m.source_type != SOURCE_DOCUMENT
    )
    return LinkedProofChain(
        chain_id=_chain_id(evidence_ids),
        project_id=_mode([m.project_id for m in members]),
        project_title=project_title,
        skill_name=skill_name,
        canonical_skill_name=canonical,
        chain_label=_chain_label(canonical or skill_name, project_title),
        linked_evidence_ids=evidence_ids,
        source_types_present=_ordered_source_types(members),
        primary_source_type=_primary_source_type(members),
        connection_reasons=_connection_reasons(members, skill_tokens),
        proof_strength_summary=_strength_summary(members),
        limitations=_chain_limitations(members),
        public_safe=public_safe,
        artifacts=tuple(members),
    )


def _chain_sort_key(chain: LinkedProofChain) -> tuple[int, int, str]:
    """Strongest chains first, then ``chain_id`` for a fully deterministic order."""
    strengths = chain.proof_strength_summary.get("strengths_present") or []
    best_rank = min((_STRENGTH_RANK.get(s, 9) for s in strengths), default=9)
    return (best_rank, -len(chain.linked_evidence_ids), chain.chain_id)


def _try_union(
    uf: _UnionFind,
    comp_pids: dict[int, set[str]],
    a: int,
    b: int,
) -> bool:
    """Union ``a`` and ``b`` UNLESS it would merge two conflicting explicit projects.

    This is the **component-level** hard blocker for explicit ``project_id``: a
    union is allowed only when the *merged* component would still carry at most one
    distinct explicit ``project_id``. So no sequence of links — whether inside one
    structural-token bucket or transitively across several — can ever collapse
    ``project-a`` and ``project-b`` into one chain. ``comp_pids`` maps each current
    union-find root to the set of explicit ``project_id`` values in its component
    and is kept in sync on every successful union (the lower index stays the root,
    mirroring :meth:`_UnionFind.union`, so roots remain deterministic).

    Returns ``True`` when the union happened (or was already merged), ``False`` when
    it was blocked as a conflicting-project merge.
    """
    ra, rb = uf.find(a), uf.find(b)
    if ra == rb:
        return True
    merged = comp_pids[ra] | comp_pids[rb]
    if len(merged) >= 2:
        return False  # would put two conflicting explicit project_ids in one chain
    uf.union(a, b)
    new_root, old_root = min(ra, rb), max(ra, rb)
    comp_pids[new_root] = merged
    comp_pids.pop(old_root, None)
    return True


def _project_signal_bridges(
    project_buckets: dict[tuple[str, str], list[int]],
    explicit_pids: list[set[str]],
) -> set[int]:
    """Project-less artifacts compatible with >= 2 conflicting explicit projects.

    The Layer-1 counterpart of :func:`_bridge_artifacts`. A ``project_id``-less
    artifact that shares a project-level *title* or *repo* signal with artifacts
    drawn from *more than one* explicit ``project_id`` group is genuinely
    ambiguous: it would otherwise attach (in Layer 1) to whichever conflicting
    group happens to sit first in its bucket — an arbitrary, input-order-dependent
    choice that changes chain membership and ``chain_id``. Such an artifact must
    not attach through Layer-1 project signals at all, so it is dropped from the
    title / repo buckets entirely (its own ``project_id`` bucket never holds it,
    since it has none).

    The reachable-project set is computed from the seeded *explicit* per-artifact
    project ids (before any union), so the result is order-independent. Together
    with the component-level guard in :func:`_try_union`, this keeps Layer-1
    linking deterministic: a neutral artifact compatible with two conflicting
    projects ends up in neither, never arbitrarily in one.
    """
    reach: dict[int, set[str]] = defaultdict(set)
    for (kind, _value), bucket in project_buckets.items():
        if kind == "project_id" or len(bucket) < 2:
            continue  # a project_id bucket only ever holds artifacts carrying it
        bucket_pids = {pid for i in bucket for pid in explicit_pids[i]}
        for i in bucket:
            if not explicit_pids[i]:  # project-less artifact in a title/repo bucket
                reach[i] |= bucket_pids
    return {i for i, pids in reach.items() if len(pids) >= 2}


def _bridge_artifacts(
    uf: _UnionFind,
    comp_pids: dict[int, set[str]],
    token_carriers: dict[tuple[str, str], list[int]],
    structural_keys: set[tuple[str, str]],
) -> set[int]:
    """Project-less artifacts that span >= 2 conflicting explicit project groups.

    A ``project_id``-less artifact that shares structural tokens with artifacts from
    *more than one* explicit ``project_id`` would otherwise bridge those conflicting
    projects through different token buckets (``/predict`` → ``project-a`` in one
    bucket, ``/classify`` → ``project-b`` in another). Such an artifact must not be
    used for structural union at all, so we drop it from Layer 2 entirely (it can
    still attach via a project-level title / repo signal in Layer 1). This is the
    component-wide complement to :func:`_try_union`: the union guard blocks the
    conflicting *edge*, and dropping the bridge keeps the project-less artifact from
    arbitrarily attaching to whichever conflicting group happens to be processed
    first — preserving deterministic, order-independent chains.
    """
    reach: dict[int, set[str]] = defaultdict(set)
    for key, bucket in token_carriers.items():
        if key not in structural_keys or len(bucket) < 2:
            continue
        bucket_pids = {pid for i in bucket for pid in comp_pids[uf.find(i)]}
        for i in bucket:
            if not comp_pids[uf.find(i)]:  # project-less component
                reach[i] |= bucket_pids
    return {i for i, pids in reach.items() if len(pids) >= 2}


# ── Public API ────────────────────────────────────────────────────────────────


def link_proof_chains(
    artifacts: list[NormalizedEvidenceArtifact],
) -> list[LinkedProofChain]:
    """Link a flat set of normalized artifacts into connected proof chains.

    Deterministic union-find over two link layers:

    * **Project-level** signals (``project_id`` / distinctive ``project_title`` /
      repository) — shared by all source types, *including documents*, so a
      document corroborates the project it is attached to.
    * **Structural-token** signals (endpoint/function/file identifiers) within the
      same canonical skill — a token links artifacts only when it is structural for
      at least one of them, and documents never participate (they corroborate only).

    Returns one :class:`LinkedProofChain` per connected component, strongest first
    and otherwise ordered by a stable ``chain_id`` (so identical input always
    yields identical chains and chain ids).
    """
    artifacts = list(artifacts)
    n = len(artifacts)
    if n == 0:
        return []

    skill_tokens = _skill_tokens(artifacts)
    uf = _UnionFind(n)
    # Explicit project_id per artifact (pristine; used for order-independent bridge
    # detection in both layers). comp_pids tracks the same per *component* and is
    # kept in sync by _try_union so the conflicting-project blocker is enforced at
    # the connected-component level, not just inside one token bucket.
    explicit_pids: list[set[str]] = [
        ({str(a.project_id)} if a.project_id else set()) for a in artifacts
    ]
    comp_pids: dict[int, set[str]] = {i: set(pids) for i, pids in enumerate(explicit_pids)}

    # Layer 1 — project-level buckets (all source types, documents included).
    project_buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, artifact in enumerate(artifacts):
        for signal in _project_signals(artifact):
            project_buckets[signal].append(i)

    # Layer 2 — structural-token buckets, scoped per canonical skill. A token
    # links its carriers only when it is *structural* for at least one artifact
    # (so coincidental free-text overlap never links). Documents are excluded.
    token_carriers: dict[tuple[str, str], list[int]] = defaultdict(list)
    structural_keys: set[tuple[str, str]] = set()
    for i, artifact in enumerate(artifacts):
        if artifact.source_type == SOURCE_DOCUMENT:
            continue
        skill_key = str(artifact.canonical_skill_name or "")
        for tok in _mention_tokens(artifact, skill_tokens):
            token_carriers[(skill_key, tok)].append(i)
        for tok in _structural_tokens(artifact, skill_tokens):
            structural_keys.add((skill_key, tok))

    # Layer 1 first (sorted for determinism) so every explicit project_id anchors
    # its component before any structural token tries to link across projects.
    # Drop project-less artifacts that are compatible (via title / repo) with >= 2
    # conflicting explicit project groups: they would otherwise attach to whichever
    # group sits first in the bucket, making chain membership input-order dependent.
    project_bridges = _project_signal_bridges(project_buckets, explicit_pids)
    for _key, bucket in sorted(project_buckets.items()):
        members = [i for i in bucket if i not in project_bridges]
        for j in members[1:]:
            _try_union(uf, comp_pids, members[0], j)

    # Drop project-less artifacts that would bridge >= 2 conflicting explicit
    # project groups through different structural tokens, then apply the remaining
    # structural unions through the component-level conflicting-project guard.
    bridges = _bridge_artifacts(uf, comp_pids, token_carriers, structural_keys)
    for key in sorted(token_carriers):
        bucket = [i for i in token_carriers[key] if i not in bridges]
        if key in structural_keys and len(bucket) >= 2:
            for j in bucket[1:]:
                _try_union(uf, comp_pids, bucket[0], j)

    grouped: dict[int, list[NormalizedEvidenceArtifact]] = defaultdict(list)
    for i in range(n):
        grouped[uf.find(i)].append(artifacts[i])

    chains = [_build_chain(members, skill_tokens) for members in grouped.values()]
    chains.sort(key=_chain_sort_key)
    return chains


def link_skill_report(report: dict[str, Any]) -> list[LinkedProofChain]:
    """Normalize a Skill Report and link its evidence into proof chains.

    Convenience wrapper: reuses Step 2's :func:`normalize_skill_report` to collapse
    the report into the uniform artifact set, then links it. Pure / deterministic.
    """
    return link_proof_chains(normalize_skill_report(report))
