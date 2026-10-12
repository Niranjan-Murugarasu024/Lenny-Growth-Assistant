"""
API routes for Ship 30 for 30 essay generation, jobs, artifacts, versions, and revisions.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Union
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_app_settings, get_db, get_session_factory
from backend.app.config import Settings
from backend.app.models import ChatSession, WritingArtifact, WritingArtifactVersion
from backend.app.writing.evaluator import count_words, split_body_and_references
from backend.app.writing.html_renderer import render_markdown_to_safe_html
from backend.app.writing.job_runner import EssayJobManager, get_job_manager
from backend.app.writing.schemas import (
    EssayJobResponse,
    CreateArtifactRequest,
    GenerateArtifactRequest,
    MarkdownPreviewRequest,
    MarkdownPreviewResponse,
    RevisionRequest,
    SaveManualVersionRequest,
    WritingArtifactHistoryResponse,
    WritingArtifactListItem,
    WritingArtifactListResponse,
    WritingArtifactResponse,
    WritingArtifactVersionResponse,
    WritingArtifactVersionSummary,
    WritingBriefRequest,
)
from backend.app.writing.service import WritingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/writing", tags=["Writing Artifacts"])


def get_writing_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> WritingService:
    """Dependency provider for WritingService."""
    return WritingService(settings=settings)


def format_version_response(v: WritingArtifactVersion) -> WritingArtifactVersionResponse:

    """Helper to convert WritingArtifactVersion ORM model to Pydantic response."""
    return WritingArtifactVersionResponse(
        id=v.id,
        artifact_id=v.artifact_id,
        version_number=v.version_number,
        markdown_content=v.markdown_content,
        html_content=v.html_content,
        word_count=v.word_count,
        writing_brief=v.writing_brief or {},
        sources=v.sources or [],
        eval_metadata=v.eval_metadata or {},
        model_metadata=v.model_metadata or {},
        created_at=v.created_at.isoformat(),
    )


def format_artifact_response(artifact: WritingArtifact) -> WritingArtifactResponse:
    """Helper to convert WritingArtifact ORM model to Pydantic response."""
    versions = sorted(artifact.versions, key=lambda v: v.version_number)
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CORRUPT_ARTIFACT", "message": "Artifact has no associated versions."},
        )
    latest = versions[-1]
    return WritingArtifactResponse(
        id=artifact.id,
        session_id=artifact.session_id,
        title=artifact.title,
        artifact_type=artifact.artifact_type,
        status=artifact.status,
        latest_version=format_version_response(latest),
        created_at=artifact.created_at.isoformat(),
        updated_at=artifact.updated_at.isoformat(),
    )


def format_artifact_version_tuple(
    artifact: WritingArtifact,
    version: WritingArtifactVersion,
) -> WritingArtifactResponse:
    """Format artifact and its latest version without relying on session lazy-loading."""
    c_at = artifact.created_at.isoformat() if hasattr(artifact.created_at, "isoformat") else str(artifact.created_at)
    u_at = artifact.updated_at.isoformat() if hasattr(artifact.updated_at, "isoformat") else str(artifact.updated_at)
    v_at = version.created_at.isoformat() if hasattr(version.created_at, "isoformat") else str(version.created_at)

    return WritingArtifactResponse(
        id=artifact.id,
        session_id=artifact.session_id,
        title=artifact.title,
        artifact_type=artifact.artifact_type,
        status=artifact.status,
        latest_version=WritingArtifactVersionResponse(
            id=version.id,
            artifact_id=version.artifact_id,
            version_number=version.version_number,
            markdown_content=version.markdown_content,
            html_content=version.html_content,
            word_count=version.word_count,
            writing_brief=version.writing_brief or {},
            sources=version.sources or [],
            eval_metadata=version.eval_metadata or {},
            model_metadata=version.model_metadata or {},
            created_at=v_at,
        ),
        created_at=c_at,
        updated_at=u_at,
    )


# 1. Create and generate essay
@router.post(
    "/essays",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EssayJobResponse,
)
def create_essay(
    brief: WritingBriefRequest,
    writing_service: Annotated[WritingService, Depends(get_writing_service)],
    db: Annotated[Session, Depends(get_db)],
    sync: bool = Query(default=False, description="If true, execute synchronously (useful for test suites)"),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EssayJobResponse:
    """
    Submit a validated writing brief and trigger Ship 30 for 30 essay generation.
    Returns a job tracking handle by default (or completes synchronously if ?sync=true).
    """
    # Validate session_id exists if provided
    if brief.session_id:
        chat_session = db.get(ChatSession, brief.session_id)
        if not chat_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "SESSION_NOT_FOUND",
                    "message": f"Associated chat session '{brief.session_id}' does not exist.",
                },
            )

    job_mgr = get_job_manager(
        settings=getattr(writing_service, "_settings", None),
        session_factory=getattr(writing_service, "_session_factory", None),
    )

    if sync:


        try:
            artifact, version, evaluation = writing_service.generate_and_persist_essay(brief)
            if evaluation.passed:
                return EssayJobResponse(
                    job_id=f"sync_{artifact.id.hex[:10]}",
                    status="completed",
                    stage="Completed synchronously",
                    topic=brief.topic,
                    target_word_count=brief.target_word_count,
                    artifact_id=artifact.id,
                    version_number=version.version_number,
                    elapsed_seconds=0.0,
                )
            else:
                return EssayJobResponse(
                    job_id=f"sync_{artifact.id.hex[:10]}",
                    status="failed",
                    stage="Quality evaluation failed synchronously",
                    topic=brief.topic,
                    target_word_count=brief.target_word_count,
                    artifact_id=artifact.id,
                    version_number=version.version_number,
                    error=f"Mandatory quality evaluation failed: {'; '.join(evaluation.feedback)}",
                    elapsed_seconds=0.0,
                )
        except Exception as exc:
            logger.exception("Synchronous essay creation failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "GENERATION_FAILED", "message": f"Essay generation failed: {exc}"},
            )

    job = job_mgr.submit_job(brief, writing_service, idempotency_key=idempotency_key)
    return EssayJobResponse(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        topic=job.topic,
        target_word_count=job.target_word_count,
        artifact_id=job.artifact_id,
        version_number=job.version_number,
        error=job.error,
        elapsed_seconds=job.elapsed_seconds,
    )


# 2. Check job status
@router.get("/jobs/{job_id}", response_model=EssayJobResponse)
def get_job_status(job_id: str) -> EssayJobResponse:
    """Query the status of an ongoing or completed essay generation job."""
    job_mgr = get_job_manager()
    job = job_mgr.get_job(job_id)
    if not job:


        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": f"Job with ID '{job_id}' was not found."},
        )
    return EssayJobResponse(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        topic=job.topic,
        target_word_count=job.target_word_count,
        artifact_id=job.artifact_id,
        version_number=job.version_number,
        error=job.error,
        elapsed_seconds=job.elapsed_seconds,
    )


# 3. Preview arbitrary Markdown safely
@router.post("/preview", response_model=MarkdownPreviewResponse)
def preview_markdown(
    payload: MarkdownPreviewRequest,
) -> MarkdownPreviewResponse:
    """
    Safely render and sanitize arbitrary Markdown into HTML preview.
    Uses the canonical Markdown renderer and Rust-based nh3 sanitizer.
    """
    html = render_markdown_to_safe_html(payload.markdown_content, include_styles=True)
    body, _ = split_body_and_references(payload.markdown_content)
    wc = count_words(body)
    return MarkdownPreviewResponse(
        html_content=html,
        word_count=wc,
    )


# 4. List artifacts
@router.get("/artifacts", response_model=WritingArtifactListResponse)
def list_artifacts(
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session_id: UUID | None = Query(default=None),
) -> WritingArtifactListResponse:
    """Retrieve paginated list of writing artifacts."""
    base_stmt = select(WritingArtifact)
    if session_id:
        base_stmt = base_stmt.where(WritingArtifact.session_id == session_id)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = db.scalar(count_stmt) or 0

    stmt = base_stmt.order_by(WritingArtifact.updated_at.desc()).offset(offset).limit(limit)
    artifacts = db.scalars(stmt).all()

    items = []
    for art in artifacts:
        versions = sorted(art.versions, key=lambda v: v.version_number)
        latest_ver_num = versions[-1].version_number if versions else 1
        latest_wc = versions[-1].word_count if versions else 0
        items.append(
            WritingArtifactListItem(
                id=art.id,
                session_id=art.session_id,
                title=art.title,
                artifact_type=art.artifact_type,
                status=art.status,
                latest_version_number=latest_ver_num,
                latest_word_count=latest_wc,
                created_at=art.created_at.isoformat(),
                updated_at=art.updated_at.isoformat(),
            )
        )

    return WritingArtifactListResponse(
        artifacts=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# 4b. Create artifact directly (Markdown or HTML)
@router.post(
    "/artifacts",
    status_code=status.HTTP_201_CREATED,
    response_model=WritingArtifactResponse,
)
def create_artifact(
    payload: CreateArtifactRequest,
    writing_service: Annotated[WritingService, Depends(get_writing_service)],
    db: Annotated[Session, Depends(get_db)],
) -> WritingArtifactResponse:
    """Directly create and persist a new Markdown or HTML artifact with server-side sanitization."""
    if payload.session_id:
        sess = db.get(ChatSession, payload.session_id)
        if not sess:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "SESSION_NOT_FOUND", "message": f"Chat session '{payload.session_id}' not found."},
            )
    try:
        artifact, version = writing_service.create_artifact(
            title=payload.title,
            content=payload.content,
            artifact_type=payload.artifact_type,
            session_id=payload.session_id,
            sources=payload.sources,
            writing_brief=payload.writing_brief,
        )
        return format_artifact_version_tuple(artifact, version)
    except Exception as exc:
        logger.exception("Failed to create artifact: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "ARTIFACT_CREATION_FAILED", "message": str(exc)},
        )


# 4c. Generate artifact from conversation context
@router.post(
    "/artifacts/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=WritingArtifactResponse,
)
def generate_artifact_from_conversation(
    payload: GenerateArtifactRequest,
    writing_service: Annotated[WritingService, Depends(get_writing_service)],
    db: Annotated[Session, Depends(get_db)],
) -> WritingArtifactResponse:
    """Generate a Markdown document or HTML/CSS snippet from conversation context."""
    sess = db.get(ChatSession, payload.session_id)
    if not sess:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SESSION_NOT_FOUND", "message": f"Chat session '{payload.session_id}' not found."},
        )
    try:
        artifact, version = writing_service.generate_artifact_from_conversation(
            session_id=payload.session_id,
            prompt=payload.prompt,
            artifact_type=payload.artifact_type,
            title=payload.title,
        )
        return format_artifact_version_tuple(artifact, version)
    except Exception as exc:
        logger.exception("Failed to generate artifact: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "ARTIFACT_GENERATION_FAILED", "message": str(exc)},
        )


# 5. Retrieve an artifact
@router.get("/artifacts/{artifact_id}", response_model=WritingArtifactResponse)
def get_artifact(
    artifact_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> WritingArtifactResponse:
    """Retrieve full artifact metadata and latest version preview."""
    artifact = db.get(WritingArtifact, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": f"Artifact '{artifact_id}' does not exist."},
        )
    return format_artifact_response(artifact)


# 4. Retrieve version history
@router.get("/artifacts/{artifact_id}/versions", response_model=WritingArtifactHistoryResponse)
def get_artifact_versions(
    artifact_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> WritingArtifactHistoryResponse:
    """Retrieve ordered list of version summaries for an artifact."""
    artifact = db.get(WritingArtifact, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": f"Artifact '{artifact_id}' does not exist."},
        )

    versions = sorted(artifact.versions, key=lambda v: v.version_number)
    summaries = [
        WritingArtifactVersionSummary(
            id=v.id,
            version_number=v.version_number,
            word_count=v.word_count,
            created_at=v.created_at.isoformat(),
        )
        for v in versions
    ]
    return WritingArtifactHistoryResponse(
        artifact_id=artifact.id,
        title=artifact.title,
        versions=summaries,
    )


# 5. Retrieve a specific immutable version
@router.get("/artifacts/{artifact_id}/versions/{version_number}", response_model=WritingArtifactVersionResponse)
def get_specific_version(
    artifact_id: UUID,
    version_number: int,
    db: Annotated[Session, Depends(get_db)],
) -> WritingArtifactVersionResponse:
    """Retrieve exact immutable snapshot of a specific artifact version."""
    stmt = (
        select(WritingArtifactVersion)
        .where(
            WritingArtifactVersion.artifact_id == artifact_id,
            WritingArtifactVersion.version_number == version_number,
        )
    )
    version = db.scalar(stmt)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "VERSION_NOT_FOUND",
                "message": f"Version {version_number} does not exist for artifact '{artifact_id}'.",
            },
        )
    return format_version_response(version)


# 6. Revise an essay
@router.post(
    "/artifacts/{artifact_id}/revisions",
    status_code=status.HTTP_201_CREATED,
    response_model=Union[WritingArtifactResponse, EssayJobResponse],
)
def revise_artifact(
    artifact_id: UUID,
    payload: RevisionRequest,
    writing_service: Annotated[WritingService, Depends(get_writing_service)],
    db: Annotated[Session, Depends(get_db)],
    sync: Annotated[bool, Query(description="Run revision synchronously instead of queueing durable background job")] = False,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    """
    Submit revision instructions to create a new immutable version for an existing essay.
    By default runs asynchronously via the durable background worker, returning a trackable job ID.
    Supports ?sync=true for synchronous test suites.
    """
    artifact = db.get(WritingArtifact, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": f"Artifact '{artifact_id}' does not exist."},
        )

    job_mgr = get_job_manager(
        settings=getattr(writing_service, "_settings", None),
        session_factory=getattr(writing_service, "_session_factory", None),
    )

    if sync:
        try:
            updated_art, new_ver, eval_result = writing_service.revise_artifact(
                artifact_id=artifact_id,
                instructions=payload.instructions,
                target_word_count=payload.target_word_count,
            )
            db.refresh(artifact)
            return format_artifact_response(artifact)
        except Exception as exc:
            logger.exception("Synchronous revision failed for artifact %s: %s", artifact_id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "REVISION_FAILED", "message": f"Failed to revise artifact: {exc}"},
            )

    job = job_mgr.submit_revision_job(
        artifact_id=artifact_id,
        instructions=payload.instructions,
        target_word_count=payload.target_word_count,
        writing_service=writing_service,
        idempotency_key=idempotency_key,
    )
    return EssayJobResponse(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        topic=job.topic,
        target_word_count=job.target_word_count,
        artifact_id=job.artifact_id,
        version_number=job.version_number,
        error=job.error,
        elapsed_seconds=job.elapsed_seconds,
    )


# 8. Save manual edits as a new immutable version
@router.post(
    "/artifacts/{artifact_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=WritingArtifactResponse,
)
def save_manual_version(
    artifact_id: UUID,
    payload: SaveManualVersionRequest,
    writing_service: Annotated[WritingService, Depends(get_writing_service)],
    db: Annotated[Session, Depends(get_db)],
) -> WritingArtifactResponse:
    """
    Save manually edited Markdown as a new immutable artifact version.
    Recomputes word count, renders safe HTML preview, re-evaluates document structure,
    and commits version transactionally.
    """
    artifact = db.get(WritingArtifact, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": f"Artifact '{artifact_id}' does not exist."},
        )

    try:
        updated_art, new_ver, eval_result = writing_service.save_manual_version(
            artifact_id=artifact_id,
            markdown_content=payload.markdown_content,
            note=payload.note,
        )
        db.refresh(artifact)
        return format_artifact_response(artifact)
    except Exception as exc:
        logger.exception("Manual version save failed for artifact %s: %s", artifact_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SAVE_FAILED", "message": f"Failed to save version: {exc}"},
        )

