from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.deps import get_app_settings, get_chat_provider_dep, get_db
from backend.app.api.schemas import HealthLiveResponse, HealthReadyResponse
from backend.app.config import Settings
from backend.app.rag.provider_base import ChatProvider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health/live", response_model=HealthLiveResponse)
def get_liveness() -> HealthLiveResponse:
    """Lightweight liveness probe indicating process is active."""
    return HealthLiveResponse(status="ok", service="lenny-growth-assistant")


@router.get("/health/ready", response_model=HealthReadyResponse)
def get_readiness(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    provider: Annotated[ChatProvider, Depends(get_chat_provider_dep)],
) -> HealthReadyResponse:
    """
    Readiness probe verifying PostgreSQL connectivity and chat provider status.

    Checks model availability without triggering a text-generation request.
    """
    db_ready = False
    db_details: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1;"))
        db_ready = True
        db_details = {
            "status": "connected",
            "database": settings.postgres_db or "lenny_growth",
        }
    except Exception as exc:
        logger.error("Database readiness check failed: %s", exc)
        db_details = {
            "status": "unavailable",
            "error": "database_connection_failed",
        }

    if hasattr(provider, "check_server_health"):
        provider_health = provider.check_server_health()
    else:
        provider_health = provider.check_health()

    inference_ready = provider_health.get("available", False)
    provider_name = (
        provider.name
        if isinstance(provider.name, str)
        else (settings.chat_provider or "ollama")
    )
    model_name = (
        provider.model_name
        if isinstance(provider.model_name, str)
        else (settings.ollama_chat_model if provider_name == "ollama" else (settings.litellm_model or ""))
    )
    inference_details = {
        "provider": provider_name,
        "status": provider_health.get("status", "available" if inference_ready else "unavailable"),
        "configured_model": model_name,
        "model_available": provider_health.get("model_available", False),
    }
    if not inference_ready:
        inference_details["error"] = provider_health.get("error", "provider_unreachable")

    is_overall_ready = db_ready and inference_ready

    # Safe Redis connectivity and queue inspection
    redis_details: dict[str, Any] = {"status": "not_configured"}
    queue_details: dict[str, Any] = {"status": "in_memory"}
    if settings.redis_url:
        try:
            import redis as py_redis
            r = py_redis.from_url(settings.redis_url, socket_connect_timeout=1.0)
            if r.ping():
                q_len = r.llen("lenny:writing:jobs")
                redis_details = {"status": "connected", "url": settings.redis_url.split("@")[-1]}
                queue_details = {"status": "active", "pending_jobs": q_len}
            else:
                redis_details = {"status": "unreachable"}
        except Exception as exc:
            redis_details = {"status": "unavailable", "error": str(exc)}

    if not is_overall_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SERVICE_NOT_READY",
                "status": "not_ready",
                "database": db_details,
                "inference": inference_details,
                "redis": redis_details,
                "queue": queue_details,
            },
        )

    return HealthReadyResponse(
        status="ready",
        database=db_details,
        inference=inference_details,
        redis=redis_details,
        queue=queue_details,
    )

