from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceKind = Literal["scholar_labs", "pdf_drop", "bibtex_import", "doi_import", "manual"]


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
    citation_status: str = "partial"
    links: list[Link] = Field(default_factory=list)
    summary: str = "No summary yet."
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
            "citation_status": self.citation_status,
            "links": [link.model_dump(exclude_none=True) for link in self.links],
        }


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    date: str
    prompt: str
    source: str = "google_scholar_labs"
    exported_at: str
    export_file: str
    raw_export_file: str
    result_count: int
    results: list[ScholarLabsResult] = Field(default_factory=list)
    paper_slugs: list[str] = Field(default_factory=list)
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


class MatchDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate: PdfCandidate | None = None
    score: int = 0
    decision: Literal["auto", "review", "skip"] = "skip"
    reason: str = ""
