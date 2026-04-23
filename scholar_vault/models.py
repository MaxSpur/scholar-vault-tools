from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceKind = Literal["scholar_labs", "pdf_drop", "bibtex_import", "doi_import", "manual"]
RunResultStatus = Literal["selected", "candidate", "unmatched", "skipped"]
RunPdfStatus = Literal["attached", "missing", "unmatched"]
ManifestDecision = Literal["accepted", "rejected", "skipped", "unresolved"]
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

    @property
    def venue(self) -> str | None:
        return self.venue_preview or self.publisher_or_host


class ScholarLabsExport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str
    source: str
    exported_at: str
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
    status: str = "active"
    pdf_status: str = "missing"
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
            "status": self.status,
            "pdf_status": self.pdf_status,
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
            "abstract": self.abstract,
            "abstract_status": self.abstract_status,
            "abstract_source": self.abstract_source,
            "abstract_source_url": self.abstract_source_url,
            "abstract_confidence": self.abstract_confidence,
            "abstract_last_checked": self.abstract_last_checked,
            "abstract_enriched_at": self.abstract_enriched_at,
            "abstract_input_fingerprint": self.abstract_input_fingerprint,
            "abstract_lock": self.abstract_lock,
            "links": [link.model_dump(exclude_none=True) for link in self.links],
            "summary_sources": [
                source.model_dump(exclude_none=True) for source in self.summary_sources
            ],
        }


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    date: str
    prompt: str
    title: str | None = None
    note_file: str | None = None
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
