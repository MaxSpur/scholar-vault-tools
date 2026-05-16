from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .titles import clean_paper_title

SourceKind = Literal["scholar_labs", "pdf_drop", "bibtex_import", "doi_import", "manual"]
RunResultStatus = Literal["selected", "candidate", "unmatched", "skipped"]
RunPdfStatus = Literal["attached", "missing", "unmatched"]
ManifestDecision = Literal["accepted", "rejected", "skipped", "unresolved"]
DiscoverySource = Literal["openalex", "semantic_scholar"]
DiscoveryStatus = Literal["candidate", "selected", "rejected", "imported"]
DoiStatus = Literal["missing", "detected", "resolved", "verified", "ambiguous", "unresolved"]
CitationStatus = Literal[
    "missing",
    "generated",
    "verified",
    "ambiguous",
    "unresolved",
    "manual_lock",
]
AbstractStatus = Literal[
    "missing",
    "resolved",
    "verified",
    "ambiguous",
    "unresolved",
    "manual_lock",
]
QueueKind = Literal[
    "compile_paper",
    "update_synthesis",
    "check_contradiction",
    "discover_sources",
    "scholar_labs_prompt",
    "improve_tool",
    "review_feedback",
    "lint_fix",
]
QueueStatus = Literal["open", "planned", "running", "drafted", "blocked", "done", "rejected"]
QueuePriority = Literal["low", "normal", "high"]
QueueCreatedBy = Literal["user", "import", "lint", "eval", "agent", "automation", "feedback"]
RequiredEvidence = Literal["pdf", "metadata", "web", "none"]
FeedbackTargetType = Literal[
    "paper_digest",
    "synthesis",
    "concept",
    "task",
    "query",
    "prompt_pack",
    "tool_behavior",
]
FeedbackVerdict = Literal["useful", "needs_fix", "rejected", "stale", "excellent"]


class Link(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    url: str
    kind: str | None = None
    count: int | None = None


class RationalePoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = ""
    text: str


class SummarySource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run: str
    prompt: str | None = None
    rank: int | None = None
    summary: str
    rationale_points: list[RationalePoint] = Field(default_factory=list)


class ScholarLabsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rank: int
    scholar_cid: str | None = None
    title: str
    authors_preview: str | None = ""
    year: int | None = None
    venue_preview: str | None = None
    publisher_or_host: str | None = None
    summary: str | None = ""
    rationale_points: list[RationalePoint] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return clean_paper_title(value)

    @property
    def venue(self) -> str | None:
        return self.venue_preview or self.publisher_or_host


class ScholarLabsExport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str
    source: str
    exported_at: str
    title: str | None = None
    prompt: str = ""
    results: list[ScholarLabsResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_export(self) -> ScholarLabsExport:
        if self.source != "google_scholar_labs":
            return self

        prompt = self.prompt.strip()
        if not prompt:
            raise ValueError(
                "Invalid Google Scholar Labs export: prompt is missing. "
                "This usually means the browser exporter ran on the wrong page "
                "or the Scholar-specific gs_* selectors are broken."
            )
        if prompt == "Google Scholar":
            raise ValueError(
                "Invalid Google Scholar Labs export: prompt is 'Google Scholar'. "
                "This usually means the browser exporter ran on the wrong page "
                "or the Scholar-specific gs_* selectors are broken."
            )
        if not self.results:
            raise ValueError(
                "Invalid Google Scholar Labs export: no results were found. "
                "This usually means the browser exporter ran on the wrong page "
                "or the Scholar-specific gs_* selectors are broken."
            )
        return self


class RunResultRecord(ScholarLabsResult):
    status: RunResultStatus = "candidate"
    pdf_status: RunPdfStatus = "missing"
    paper_card: str | None = None
    proposed_pdf: str | None = None
    proposed_sha256: str | None = None
    score: int | None = None
    decision: ManifestDecision | None = None


class SourceCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    type: str = "paper"
    citekey: str | None = None
    title: str
    authors_preview: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    pdf: str | None = None
    source_kind: SourceKind = "manual"
    scholar_cid: str | None = None
    discovered_in: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    publication_keywords_status: str = "missing"
    publication_keywords_source: str | None = None
    status: str = "active"
    pdf_status: str = "missing"
    reading_status: str = "unread"
    compiled_status: str = "uncompiled"
    review_status: str = "unreviewed"
    last_read_at: str | None = None
    last_compiled_at: str | None = None
    last_reviewed_at: str | None = None
    evidence_level: str = "unknown"
    paper_digest: str | None = None
    linked_queries: list[str] = Field(default_factory=list)
    linked_query_paths: list[str] = Field(default_factory=list)
    linked_projects: list[str] = Field(default_factory=list)
    doi_status: DoiStatus = "missing"
    doi_source: str | None = None
    doi_confidence: float | None = None
    citation_status: str = "missing"
    citation_source: str | None = None
    citation_last_checked: str | None = None
    citation_enriched_at: str | None = None
    citation_input_fingerprint: str | None = None
    citation_retries: int = 0
    citation_skip_reason: str | None = None
    metadata_lock: bool = False
    enrichment_status: str = "missing"
    enrichment_missing: list[str] = Field(default_factory=list)
    enrichment_refresh: bool = False
    abstract: str | None = None
    abstract_status: AbstractStatus = "missing"
    abstract_source: str | None = None
    abstract_source_url: str | None = None
    abstract_confidence: float | None = None
    abstract_last_checked: str | None = None
    abstract_enriched_at: str | None = None
    abstract_input_fingerprint: str | None = None
    abstract_lock: bool = False
    links: list[Link] = Field(default_factory=list)
    summary: str = "No summary yet."
    summary_sources: list[SummarySource] = Field(default_factory=list)
    why_this_source_matters: list[RationalePoint] = Field(default_factory=list)
    notes: str = ""

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return clean_paper_title(value)

    @field_validator("linked_queries", "linked_query_paths", "linked_projects", mode="before")
    @classmethod
    def coerce_link_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def frontmatter(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "citekey": self.citekey,
            "title": self.title,
            "authors_preview": self.authors_preview,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "url": self.url,
            "pdf": self.pdf,
            "source_kind": self.source_kind,
            "scholar_cid": self.scholar_cid,
            "discovered_in": self.discovered_in,
            "topics": self.topics,
            "keywords": self.keywords,
            "publication_keywords_status": self.publication_keywords_status,
            "publication_keywords_source": self.publication_keywords_source,
            "status": self.status,
            "pdf_status": self.pdf_status,
            "reading_status": self.reading_status,
            "compiled_status": self.compiled_status,
            "review_status": self.review_status,
            "last_read_at": self.last_read_at,
            "last_compiled_at": self.last_compiled_at,
            "last_reviewed_at": self.last_reviewed_at,
            "evidence_level": self.evidence_level,
            "paper_digest": self.paper_digest,
            "linked_queries": self.linked_queries,
            "linked_query_paths": self.linked_query_paths,
            "linked_projects": self.linked_projects,
            "doi_status": self.doi_status,
            "doi_source": self.doi_source,
            "doi_confidence": self.doi_confidence,
            "citation_status": self.citation_status,
            "citation_source": self.citation_source,
            "citation_last_checked": self.citation_last_checked,
            "citation_enriched_at": self.citation_enriched_at,
            "citation_input_fingerprint": self.citation_input_fingerprint,
            "citation_retries": self.citation_retries,
            "citation_skip_reason": self.citation_skip_reason,
            "metadata_lock": self.metadata_lock,
            "enrichment_status": self.enrichment_status,
            "enrichment_missing": self.enrichment_missing,
            "enrichment_refresh": self.enrichment_refresh,
            "abstract_status": self.abstract_status,
            "abstract_source": self.abstract_source,
            "abstract_source_url": self.abstract_source_url,
            "abstract_confidence": self.abstract_confidence,
            "abstract_last_checked": self.abstract_last_checked,
            "abstract_enriched_at": self.abstract_enriched_at,
            "abstract_input_fingerprint": self.abstract_input_fingerprint,
            "abstract_lock": self.abstract_lock,
            "links": [link.model_dump(exclude_none=True) for link in self.links],
        }


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    date: str
    prompt: str
    title: str | None = None
    note_file: str | None = None
    prompt_pack: str | None = None
    query: str | None = None
    source: str = "google_scholar_labs"
    exported_at: str
    export_file: str
    raw_export_file: str
    staging_folder: str = ""
    result_count: int
    include_without_pdf: bool = False
    archive_matched_from_staging: bool = False
    results: list[RunResultRecord] = Field(default_factory=list)
    matched_files: list[str] = Field(default_factory=list)
    unmatched_files: list[str] = Field(default_factory=list)


class DiscoveryCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source: DiscoverySource
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    venue: str | None = None
    abstract: str | None = None
    cited_by_count: int | None = None
    seed_citekey: str | None = None
    query: str | None = None
    project: str | None = None
    reason: str = ""
    status: DiscoveryStatus = "candidate"
    linked_prompt_pack: str | None = None
    linked_run: str | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return clean_paper_title(value)

    @field_validator("authors", mode="before")
    @classmethod
    def coerce_authors(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []


class ImportLogEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_path: str
    destination_path: str | None = None
    status: str
    note: str | None = None
    score: int | None = None


class ImportLog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command: str
    created_at: str
    entries: list[ImportLogEntry] = Field(default_factory=list)


class ToolImprovementTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_repo: str = "scholar-vault-tools"
    problem: str = ""
    reproduction: str = ""
    expected_behavior: str = ""
    actual_behavior: str = ""
    proposed_cli_change: str = ""
    tests_to_add: list[str] = Field(default_factory=list)


class QueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    kind: QueueKind
    status: QueueStatus = "open"
    priority: QueuePriority = "normal"
    created_at: str
    updated_at: str
    created_by: QueueCreatedBy = "user"
    project: str | None = None
    query: str | None = None
    citekeys: list[str] = Field(default_factory=list)
    runs: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    required_evidence: RequiredEvidence = "none"
    success_criteria: str = ""
    notes: str = ""
    stable_key: str | None = None
    linked_feedback: list[str] = Field(default_factory=list)
    linked_operations: list[str] = Field(default_factory=list)
    tool_improvement: ToolImprovementTask | None = None

    @field_validator(
        "citekeys",
        "runs",
        "files",
        "linked_feedback",
        "linked_operations",
        mode="before",
    )
    @classmethod
    def coerce_string_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def coerce_timestamps(cls, value: object) -> str:
        if isinstance(value, str):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


class OperationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    kind: str
    started_at: str
    finished_at: str | None = None
    agent: str | None = None
    model: str | None = None
    command: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    files_changed: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)
    result: str = "logged"
    linked_queue_items: list[str] = Field(default_factory=list)
    linked_feedback: list[str] = Field(default_factory=list)

    @field_validator(
        "files_changed",
        "evidence_used",
        "checks_run",
        "linked_queue_items",
        "linked_feedback",
        mode="before",
    )
    @classmethod
    def coerce_record_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def coerce_timestamps(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    target: str
    target_type: FeedbackTargetType
    verdict: FeedbackVerdict
    notes: str = ""
    created_at: str
    linked_operation: str | None = None
    linked_queue_item: str | None = None

    @field_validator("created_at", mode="before")
    @classmethod
    def coerce_timestamp(cls, value: object) -> str:
        if isinstance(value, str):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


class PdfCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    title: str | None = None
    doi: str | None = None
    year: int | None = None
    text_excerpt: str = ""
    metadata: dict[str, str | None] = Field(default_factory=dict)
    sha256: str | None = None
    size: int | None = None


class MatchDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate: PdfCandidate | None = None
    score: int = 0
    decision: Literal["auto", "review", "skip"] = "skip"
    reason: str = ""


class MatchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rank: int
    scholar_cid: str | None = None
    result_title: str
    authors_preview: str | None = None
    year: int | None = None
    venue: str | None = None
    summary: str | None = None
    pdf_path: str
    pdf_filename: str
    score: int
    match_reason: str
    proposed_decision: Literal["auto", "review", "skip"]
    inferred_title: str | None = None
    inferred_doi: str | None = None
    inferred_year: int | None = None
    text_excerpt: str = ""


class MatchReviewAbort(RuntimeError):
    """Raised when a reviewer aborts the whole import instead of rejecting one match."""


class ImportCanceled(RuntimeError):
    """Raised when a user declines to continue an import before changes are applied."""


class ImportManifestEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rank: int | None = None
    scholar_cid: str | None = None
    result_title: str | None = None
    original_path: str | None = None
    original_sha256: str | None = None
    proposed_match: str | None = None
    score: int | None = None
    decision: ManifestDecision = "unresolved"
    destination_path: str | None = None
    copied: bool = False
    moved: bool = False
    archived_original_path: str | None = None
    paper_card: str | None = None
    paper_card_created: bool = False
    card_preexisting: bool = False
    card_before: dict[str, Any] | None = None
    verified: bool = False
    note: str | None = None


class ImportManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    export_file: str
    staging_folder: str
    created_at: str
    entries: list[ImportManifestEntry] = Field(default_factory=list)
