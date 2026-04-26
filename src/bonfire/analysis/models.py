"""Project analysis models — Pydantic shapes for code-graph studies.

Frozen Pydantic models used across the Cartographer pipeline.

``CartographerBudget`` holds all tunables; defaults are pinned by
the §12 H3 default pin table and mirrored byte-for-byte by

``RankedNode`` / ``StudyMetadata`` / ``ProjectAnalysis`` are the
Projector's immutable output types. ``ProjectAnalysis`` is the self-
describing, cache-ready scan artefact consumed by Wave 2b.

This module must stay importable without loading ``tiktoken``,
``networkx``, ``grep_ast``, or ``tree_sitter``.
Only ``pydantic`` + stdlib here.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — Pydantic runtime type resolution
from pathlib import Path  # noqa: TC003 — Pydantic runtime type resolution
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ─── Type aliases ──────────────────────────────────────────────────────

NodeId = str  # "src/bonfire/engine.py::Engine.dispatch"
RelPath = str  # "src/bonfire/engine.py"

NodeKind = Literal[
    "module",
    "class",
    "function",
    "method",
    "constant",
    "import",
]


# ─── CartographerBudget ────────────────────────────────────────────────


class CartographerBudget(BaseModel):
    """Frozen budget of Cartographer tunables (BON-226 §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_tokens: int = Field(default=1024, ge=1)
    token_tolerance: float = Field(default=0.15, ge=0.0, le=1.0)
    token_encoding: str = Field(default="cl100k_base")
    alpha: float = Field(default=0.85, ge=0.0, le=1.0)
    max_iter: int = Field(default=100, ge=1)
    tol: float = Field(default=1e-6, gt=0.0)
    max_ident_defs: int = Field(default=20, ge=1)
    min_cross_lang_ident_len: int = Field(default=8, ge=1)
    top_k_projection: int = Field(default=500, ge=1)
    max_file_size_bytes: int = Field(default=1_000_000, ge=1)
    languages: tuple[str, ...] = Field(default=())
    ignore_globs: tuple[str, ...] = Field(
        default=("node_modules/**", "target/**", "__pycache__/**", ".venv/**")
    )
    enrichment_enabled: bool = Field(default=False)

    # ─── BON-294 Wave 2c.1 enrichment delta ──────────────────────────
    enrichment_mode: Literal["off", "harvest", "llm"] = Field(default="harvest")
    enrichment_top_n: int = Field(default=20, ge=1, le=500)
    enrichment_batch_size: int = Field(default=5, ge=1, le=50)
    enrichment_max_budget_usd: float = Field(default=0.10, ge=0.0)
    min_harvest_words: int = Field(default=4, ge=1)


# ─── RankedNode ────────────────────────────────────────────────────────


class RankedNode(BaseModel):
    """One symbol surviving ranking + projection. Immutable.

    §12 M5 — ``snippet`` is never empty in a valid ``ProjectAnalysis``; the
    Projector filters out any node whose render collapsed to an empty
    string before materialising a ``RankedNode``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: NodeId
    kind: NodeKind
    path: RelPath
    line_start: int = Field(ge=0)
    line_end: int = Field(ge=0)
    snippet: str = Field(
        min_length=1,
        description="Projected TreeContext signature text. Never empty (§12 M5). "
        "The non-empty invariant is enforced at the model layer via "
        "``min_length=1`` so an external caller (BON-231 composition root, "
        "a future plugin, the serializer round-trip path) cannot construct "
        "an invalid ``RankedNode`` with ``snippet=''``.",
    )
    tokens: int = Field(
        ge=0,
        description="Raw tiktoken count — no multiplier (§12 M1).",
    )
    file_rank: float = Field(ge=0.0)
    symbol_rank: float = Field(ge=0.0)
    edge_weight_in: float = Field(ge=0.0)

    # ─── BON-294 Wave 2c.1 enrichment delta ──────────────────────────
    summary: str | None = Field(default=None, max_length=500)
    summary_source: Literal[
        "docstring",
        "module_doc",
        "readme",
        "git_log",
        "llm",
        "none",
    ] = Field(default="none")

    @field_validator("summary")
    @classmethod
    def _summary_strip_or_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None

    @model_validator(mode="after")
    def _summary_source_consistency(self) -> RankedNode:
        if self.summary is None and self.summary_source != "none":
            raise ValueError(f"summary_source={self.summary_source!r} but summary is None")
        if self.summary is not None and self.summary_source == "none":
            raise ValueError("summary populated but summary_source='none'")
        return self


# ─── StudyMetadata ─────────────────────────────────────────────────────


class StudyMetadata(BaseModel):
    """Scan-time provenance. Wave 2b reads this for cache validity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    project_root: Path
    scanned_at: datetime
    git_sha: str | None = Field(default=None)

    structural_only: bool
    file_count: int = Field(ge=0)
    node_count_total: int = Field(ge=0)
    node_count_projected: int = Field(ge=0)

    budget_tokens: int = Field(ge=0)
    budget_used: int = Field(ge=0)
    budget_tolerance: float = Field(ge=0.0, le=1.0)

    language_counts: dict[str, int] = Field(default_factory=dict)
    skipped_files: tuple[tuple[RelPath, str], ...] = Field(default=())

    cartographer_version: str
    tree_sitter_language_pack_version: str
    tiktoken_version: str
    networkx_version: str
    fingerprint: str

    elapsed_ms_parse: int = Field(ge=0)
    elapsed_ms_rank: int = Field(ge=0)
    elapsed_ms_project: int = Field(ge=0)


# ─── GapFinding ──────────────────────────────────────────────────────


class GapFinding(BaseModel):
    """One structural gap discovered by the Strategist scan.

    Fields mirror the minimal surface from design doc §6.3:
    ``gap_id``, ``title``, ``severity``, ``size``, ``urgency``, ``category``.
    Structural-only — no enriched fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gap_id: str
    title: str
    severity: int = Field(default=3, ge=0, le=4)
    size: str = Field(default="small")
    urgency: int = Field(default=3, ge=0, le=4)
    category: str = Field(default="general")


# ─── ProjectAnalysis ────────────────────────────────────────────────────


class ProjectAnalysis(BaseModel):
    """Project-analysis output. Immutable, self-describing, cache-ready."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_schema_version: int = Field(default=2)
    metadata: StudyMetadata
    nodes: tuple[RankedNode, ...] = Field(
        description="Symbols ordered by descending symbol_rank.",
    )
    rendered_map: str

    # BON-303 Wave 3a.4 — discovered gaps for DiscoveredIntentSource.
    # Default empty list preserves all existing tests that construct
    # ProjectAnalysis() without gaps.
    gaps: tuple[GapFinding, ...] = Field(default=())

    @field_validator("study_schema_version")
    @classmethod
    def _require_v2_schema(cls, v: int) -> int:
        # BON-294 Wave 2c.1 A10 — reject v1 cache blobs so Wave 2b cache
        # reads fall back to a fresh scan instead of silently returning
        # a study missing the enrichment fields.
        if v != 2:
            raise ValueError(f"study_schema_version must be 2, got {v}")
        return v

    def to_bytes(self) -> bytes:
        """Gzip-compressed JSON — BON-231 Wave 2b cache seam.

        The two-byte gzip magic (``\\x1f\\x8b``) lets any cache layer
        sniff the envelope without deserialising. ``gzip`` is imported
        lazily to keep ``models`` import-free of stdlib compression.
        """
        import gzip  # noqa: PLC0415 — stdlib lazy import keeps models light

        return gzip.compress(
            self.model_dump_json().encode("utf-8"),
            compresslevel=6,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ProjectAnalysis:
        """Inverse of :meth:`to_bytes`.

        Raises ``pydantic.ValidationError`` on schema drift and
        ``gzip.BadGzipFile`` / ``OSError`` on a corrupt envelope. Wave 2b
        cache reads catch those and fall back to a fresh scan.
        """
        import gzip  # noqa: PLC0415

        return cls.model_validate_json(gzip.decompress(data).decode("utf-8"))
