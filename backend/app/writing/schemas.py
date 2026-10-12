"""
Writing brief schemas and validation rules for Ship 30 for 30 essay generation.
"""
from __future__ import annotations

from enum import Enum
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EssayTone(str, Enum):
    """Supported writing tones for Ship 30 for 30 essays."""
    CONVERSATIONAL = "conversational"
    ANALYTICAL = "analytical"
    PERSUASIVE = "persuasive"
    EDUCATIONAL = "educational"


class WritingBriefRequest(BaseModel):
    """
    Validated writing brief request for generating a Ship 30 for 30-style essay.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: str = Field(
        ...,
        min_length=3,
        max_length=300,
        description="Core subject or question to investigate across Lenny's Podcast transcripts.",
        examples=["How to find and measure product-market fit"],
    )
    audience: str = Field(
        default="Product managers, founders, and growth leaders",
        min_length=3,
        max_length=200,
        description="Target readership for the essay.",
    )
    purpose: str = Field(
        default="Provide an actionable framework and strategic breakdown grounded in podcast insights.",
        min_length=5,
        max_length=300,
        description="What the essay aims to accomplish for the reader.",
    )
    central_thesis: str | None = Field(
        default=None,
        max_length=500,
        description="Optional core argument or point of view. If omitted, one is synthesized from the evidence.",
    )
    tone: EssayTone = Field(
        default=EssayTone.ANALYTICAL,
        description="Stylistic tone of the essay.",
    )
    target_word_count: int = Field(
        default=1250,
        ge=500,
        le=2500,
        description="Target word count for the essay body (default 1250 words, acceptable range 500-2500).",
    )
    include_outline: bool = Field(
        default=True,
        description="Whether to generate and evaluate an outline before drafting.",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Optional existing chat session ID to associate the artifact with.",
    )
    additional_instructions: str | None = Field(
        default=None,
        max_length=1000,
        description="Bounded supplementary guidance or constraints for drafting.",
    )

    @field_validator("topic")
    @classmethod
    def validate_topic_not_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) < 3:
            raise ValueError("Topic must contain at least 3 non-whitespace characters.")
        # Prevent prompt injection delimiters
        if re.search(r"(<\|im_start\|>|<\|im_end\|>|\[SYSTEM\]|\[INST\])", cleaned, re.IGNORECASE):
            raise ValueError("Topic contains disallowed prompt control characters.")
        return cleaned

    @field_validator("additional_instructions")
    @classmethod
    def validate_additional_instructions(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if re.search(r"(<\|im_start\|>|<\|im_end\|>|\[SYSTEM\]|\[INST\])", cleaned, re.IGNORECASE):
            raise ValueError("Additional instructions contain disallowed prompt control characters.")
        return cleaned


class RevisionRequest(BaseModel):
    """
    Validated request to revise an existing essay artifact into a new immutable version.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    instructions: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Specific revision instructions, feedback, or focus areas.",
        examples=["Expand the second section on retention metrics with more guest examples"],
    )
    target_word_count: int | None = Field(
        default=None,
        ge=500,
        le=2500,
        description="Optional updated target word count for the revision.",
    )

    @field_validator("instructions")
    @classmethod
    def validate_instructions(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) < 5:
            raise ValueError("Instructions must contain at least 5 non-whitespace characters.")
        return cleaned


class EssayJobResponse(BaseModel):
    """Status representation for a background essay generation job."""
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str
    stage: str
    topic: str
    target_word_count: int
    artifact_id: UUID | None = None
    version_number: int | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0


class WritingArtifactVersionSummary(BaseModel):
    """Lightweight metadata summary of an immutable artifact version."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    word_count: int
    created_at: str


class WritingArtifactVersionResponse(BaseModel):
    """Complete immutable version snapshot of a writing artifact."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    artifact_id: UUID
    version_number: int
    markdown_content: str
    html_content: str
    word_count: int
    writing_brief: dict[str, Any]
    sources: list[dict[str, Any]]
    eval_metadata: dict[str, Any]
    model_metadata: dict[str, Any]
    created_at: str


class WritingArtifactResponse(BaseModel):
    """Full writing artifact response with its latest version content."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID | None = None
    title: str
    artifact_type: str
    status: str
    latest_version: WritingArtifactVersionResponse
    created_at: str
    updated_at: str


class WritingArtifactHistoryResponse(BaseModel):
    """Version history listing for an artifact."""
    model_config = ConfigDict(from_attributes=True)

    artifact_id: UUID
    title: str
    versions: list[WritingArtifactVersionSummary]


class MarkdownPreviewRequest(BaseModel):
    """Request to safely render and sanitize Markdown into an HTML preview."""
    model_config = ConfigDict(extra="forbid")

    markdown_content: str = Field(
        ...,
        max_length=50000,
        description="Markdown text to render and sanitize.",
    )


class MarkdownPreviewResponse(BaseModel):
    """Response containing sanitized HTML and live body word count."""
    html_content: str
    word_count: int


class SaveManualVersionRequest(BaseModel):
    """Request to save manual Markdown edits as a new immutable artifact version."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    markdown_content: str = Field(
        ...,
        min_length=10,
        max_length=50000,
        description="Updated Markdown content for the essay.",
    )
    note: str | None = Field(
        default=None,
        max_length=200,
        description="Optional author note describing the edit.",
    )

    @field_validator("markdown_content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) < 10:
            raise ValueError("Markdown content must contain at least 10 non-whitespace characters.")
        return cleaned


class WritingArtifactListItem(BaseModel):
    """Summary item for the artifact library listing."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID | None = None
    title: str
    artifact_type: str
    status: str
    latest_version_number: int
    latest_word_count: int
    created_at: str
    updated_at: str


class WritingArtifactListResponse(BaseModel):
    """Paginated list of writing artifacts."""
    artifacts: list[WritingArtifactListItem]
    total: int
    limit: int
    offset: int


class CreateArtifactRequest(BaseModel):
    """Request payload to manually or programmatically persist a writing artifact."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(..., min_length=2, max_length=255, description="Title of the artifact")
    content: str = Field(..., min_length=5, max_length=100000, description="Markdown or HTML content")
    artifact_type: str = Field(default="document", max_length=50, description="Type: 'document', 'html', or 'essay'")
    session_id: UUID | None = Field(default=None, description="Optional associated chat session ID")
    sources: list[dict[str, Any]] | None = Field(default=None, description="Optional transcript source references")
    writing_brief: dict[str, Any] | None = Field(default=None, description="Optional brief parameters")


class GenerateArtifactRequest(BaseModel):
    """Request payload to generate and persist a document or HTML artifact from conversation."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: UUID = Field(..., description="ID of the chat session containing conversation context")
    prompt: str = Field(..., min_length=3, max_length=4000, description="Prompt specifying the artifact to generate")
    artifact_type: str = Field(default="document", max_length=50, description="Type to generate: 'document' (Markdown) or 'html' (HTML/CSS)")
    title: str | None = Field(default=None, max_length=255, description="Optional title override")


