from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthLiveResponse(BaseModel):
    """Liveness probe response."""

    status: str = "ok"
    service: str = "lenny-growth-assistant"


class HealthReadyResponse(BaseModel):
    """Readiness probe response with database, inference, and queue details."""

    status: str = "ready"
    database: dict[str, Any]
    inference: dict[str, Any]
    redis: dict[str, Any] | None = None
    queue: dict[str, Any] | None = None


class SessionCreateRequest(BaseModel):
    """Request payload to initiate a new persistent chat session."""

    title: str | None = Field(default=None, max_length=255, description="Optional title for the session")
    user_metadata: dict[str, Any] | None = Field(default=None, description="Arbitrary client metadata")


class SessionResponse(BaseModel):
    """Persistent chat session representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    user_metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """List of recent chat sessions."""

    sessions: list[SessionResponse]
    total: int


class ChatMessageRequest(BaseModel):
    """Request body for submitting a message in an existing session."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="User message content",
    )
    orchestrator: Literal["rag", "pi"] | None = Field(
        default=None,
        description="Optional orchestrator override: 'rag' or 'pi'",
    )

    @field_validator("message")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Message cannot be empty or whitespace-only.")
        return stripped


class SourceReference(BaseModel):
    """Verifiable citation linking to stored transcript chunks."""

    model_config = ConfigDict(from_attributes=True)

    citation_index: int
    is_cited: bool = True
    chunk_id: int
    chunk_index: int
    source_path: str
    guest: str
    title: str
    speaker: str | None = None
    timestamp: str | None = None
    start_time_seconds: float | None = None
    cosine_distance: float
    excerpt: str
    alternate_sources: list[str] = Field(default_factory=list)
    source_url: str | None = None
    youtube_video_id: str | None = None
    youtube_url: str | None = None


class ChatMessageResponse(BaseModel):
    """Individual conversational message record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: UUID
    role: str
    content: str
    provider: str | None = None
    model: str | None = None
    sources: list[SourceReference] | None = None
    request_id: str | None = None
    created_at: datetime


class SessionMessagesResponse(BaseModel):
    """Complete chronological message log for a session."""

    session_id: UUID
    messages: list[ChatMessageResponse]


class ErrorDetail(BaseModel):
    """Standardized error structure."""

    code: str
    message: str
    request_id: str | None = None
    details: Any = None


class ErrorResponse(BaseModel):
    """Top-level error response envelope."""

    error: ErrorDetail


class InternalSearchRequest(BaseModel):
    """Request payload for internal transcript semantic search."""

    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    max_distance: float | None = Field(default=0.30, ge=0.0, le=2.0)


class InternalChunkData(BaseModel):
    """Normalized chunk record for internal agent tools."""

    chunk_id: int
    chunk_index: int
    chunk_text: str
    cosine_distance: float | None = None
    guest: str
    title: str
    source_path: str
    speaker: str | None = None
    timestamp: str | None = None
    start_time_seconds: float | None = None
    alternate_sources: list[str] = Field(default_factory=list)


class InternalSearchResponse(BaseModel):
    """Search results response for internal agent tools."""

    query: str
    count: int
    chunks: list[InternalChunkData]


class InternalContextRequest(BaseModel):
    """Request payload for retrieving surrounding transcript chunks."""

    chunk_id: int = Field(..., ge=1)
    before: int = Field(default=1, ge=0, le=5)
    after: int = Field(default=1, ge=0, le=5)


class InternalContextResponse(BaseModel):
    """Surrounding context chunks response."""

    target_chunk_id: int
    episode_id: int
    count: int
    chunks: list[InternalChunkData]


class ModelOptionInfo(BaseModel):
    """Information about an available LLM inference option."""

    id: str
    provider: str
    model: str
    label: str
    purpose: str
    status: str  # "available", "unconfigured", "unavailable"
    status_message: str | None = None
    is_active: bool


class ModelConfigResponse(BaseModel):
    """Current active LLM configuration and available options."""

    active_provider: str
    active_model: str
    displayed_label: str
    fallback_enabled: bool
    models: list[ModelOptionInfo]


class ModelSwitchRequest(BaseModel):
    """Request payload to switch the active LLM provider and model."""

    provider: Literal["ollama", "nvidia", "litellm"]
    model: str | None = None


class LLMProviderInfo(BaseModel):
    id: str
    name: str
    model: str
    label: str
    badge: str
    category: str = "local"
    configured: bool
    status: str  # "not_configured", "configured", "connected", "unavailable", "unknown"
    status_message: str | None = None
    is_active: bool


class LLMSettingsResponse(BaseModel):
    active_provider: str
    active_model: str
    active_category: str = "local"
    displayed_label: str
    fallback_enabled: bool = False
    providers: list[LLMProviderInfo]


class UpdateLLMSettingsRequest(BaseModel):
    provider: str
    model: str | None = None


class TestLLMConnectionRequest(BaseModel):
    provider: str | None = None
    model: str | None = None


class TestLLMConnectionResponse(BaseModel):
    provider: str
    model: str
    success: bool
    connected: bool = False
    status: str
    message: str
    elapsed_seconds: float

