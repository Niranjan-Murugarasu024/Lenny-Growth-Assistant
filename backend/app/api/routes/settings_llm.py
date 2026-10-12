from __future__ import annotations

import dataclasses
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_app_settings, get_db
from backend.app.api.schemas import (
    LLMProviderInfo,
    LLMSettingsResponse,
    TestLLMConnectionRequest,
    TestLLMConnectionResponse,
    UpdateLLMSettingsRequest,
)
from backend.app.config import Settings, set_active_settings
from backend.app.database import get_db_setting, set_db_setting
from backend.app.rag.nvidia_client import NvidiaChatClient
from backend.app.rag.ollama_client import OllamaChatClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings/llm", tags=["LLM Settings"])


def build_llm_settings_response(settings: Settings, db: Session) -> LLMSettingsResponse:
    """
    Construct the authoritative LLM configuration and safe status without
    invoking billable generation requests or leaking API keys.
    """
    active_prov = (get_db_setting(db, "active_chat_provider", settings.chat_provider) or "ollama").strip().lower()
    # Normalize aliases
    if active_prov in ("cloud", "litellm"):
        active_prov = "nvidia"

    if active_prov == "ollama":
        active_model = get_db_setting(db, "active_chat_model", settings.ollama_chat_model or "qwen2.5:1.5b")
        displayed_label = f"Ollama · {active_model}"
    else:
        active_model = get_db_setting(db, "active_chat_model", settings.nvidia_model or "openai/gpt-oss-20b")
        displayed_label = f"NVIDIA NIM · {active_model}"

    # 1. Ollama status
    ollama_client = OllamaChatClient(settings=settings)
    ollama_health = ollama_client.check_server_health()
    ollama_configured = True
    ollama_status = "configured" if ollama_health.get("available") else "unavailable"
    ollama_msg = None if ollama_health.get("available") else ollama_health.get("error", "Ollama daemon unreachable")

    ollama_info = LLMProviderInfo(
        id="ollama",
        name="Ollama",
        model=settings.ollama_chat_model or "qwen2.5:1.5b",
        label=f"Ollama · {settings.ollama_chat_model or 'qwen2.5:1.5b'}",
        badge="Local",
        category="local",
        configured=ollama_configured,
        status=ollama_status,
        status_message=ollama_msg,
        is_active=(active_prov == "ollama"),
    )

    # 2. NVIDIA NIM status
    nvidia_client = NvidiaChatClient(settings=settings)
    nvidia_health = nvidia_client.check_health()
    nvidia_configured = nvidia_health.get("available", False)
    nvidia_status = nvidia_health.get("status", "not_configured")
    nvidia_msg = nvidia_health.get("error")

    nvidia_info = LLMProviderInfo(
        id="nvidia",
        name="NVIDIA NIM",
        model=settings.nvidia_model or "openai/gpt-oss-20b",
        label=f"NVIDIA NIM · {settings.nvidia_model or 'openai/gpt-oss-20b'}",
        badge="Cloud",
        category="cloud",
        configured=nvidia_configured,
        status=nvidia_status,
        status_message=nvidia_msg,
        is_active=(active_prov == "nvidia"),
    )

    active_category = "local" if active_prov == "ollama" else "cloud"
    return LLMSettingsResponse(
        active_provider=active_prov,
        active_model=active_model,
        active_category=active_category,
        displayed_label=displayed_label,
        fallback_enabled=getattr(settings, "fallback_to_ollama", False),
        providers=[ollama_info, nvidia_info],
    )


@router.get("", response_model=LLMSettingsResponse)
def get_llm_settings(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> LLMSettingsResponse:
    """Retrieve active LLM inference provider, model, and safe readiness status."""
    return build_llm_settings_response(settings, db)


@router.put("", response_model=LLMSettingsResponse)
def update_llm_settings(
    payload: UpdateLLMSettingsRequest,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> LLMSettingsResponse:
    """
    Switch active inference provider and model.
    Persists selection in PostgreSQL app_settings table so all API processes
    and background writing workers immediately use the same setting.
    Enforces security: blocks switching to NVIDIA if credentials are not configured.
    """
    target_prov = payload.provider.strip().lower()
    if target_prov in ("cloud", "litellm"):
        target_prov = "nvidia"

    if target_prov == "nvidia":
        has_key = bool(settings.nvidia_api_key or settings.litellm_api_key)
        if not has_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "MISSING_CLOUD_CREDENTIALS",
                    "message": "Cannot switch to NVIDIA: NVIDIA_API_KEY is not configured in backend environment.",
                },
            )
        target_model = payload.model or settings.nvidia_model or "openai/gpt-oss-20b"
        set_db_setting(db, "active_chat_provider", "nvidia")
        set_db_setting(db, "active_chat_model", target_model)

        updated_settings = dataclasses.replace(
            settings,
            chat_provider="nvidia",
            nvidia_model=target_model,
        )
        set_active_settings(updated_settings)
        logger.info("Authoritatively switched active chat provider to NVIDIA (model=%s)", target_model)

    elif target_prov == "ollama":
        target_model = payload.model or settings.ollama_chat_model or "qwen2.5:1.5b"
        set_db_setting(db, "active_chat_provider", "ollama")
        set_db_setting(db, "active_chat_model", target_model)

        updated_settings = dataclasses.replace(
            settings,
            chat_provider="ollama",
            ollama_chat_model=target_model,
        )
        set_active_settings(updated_settings)
        logger.info("Authoritatively switched active chat provider to Ollama (model=%s)", target_model)

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_PROVIDER",
                "message": f"Unsupported provider '{payload.provider}'. Must be 'ollama' or 'nvidia'.",
            },
        )

    return build_llm_settings_response(updated_settings, db)


@router.post("/test", response_model=TestLLMConnectionResponse)
def test_llm_connection(
    payload: TestLLMConnectionRequest,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> TestLLMConnectionResponse:
    """
    Perform an explicit live connectivity test for the selected or active provider.
    Never exposes API keys or sensitive error traces.
    """
    prov_to_test = payload.provider.strip().lower() if payload.provider else (
        get_db_setting(db, "active_chat_provider", settings.chat_provider) or "ollama"
    ).strip().lower()

    if prov_to_test in ("cloud", "litellm"):
        prov_to_test = "nvidia"

    if prov_to_test == "nvidia":
        target_model = payload.model or settings.nvidia_model or "openai/gpt-oss-20b"
        client = NvidiaChatClient(model=target_model, settings=settings)
        res = client.test_connection()
        return TestLLMConnectionResponse(
            provider="nvidia",
            model=target_model,
            success=res.get("success", False),
            connected=res.get("connected", res.get("success", False)),
            status=res.get("status", "unavailable"),
            message=res.get("message", "NVIDIA connection test completed."),
            elapsed_seconds=res.get("elapsed_seconds", 0.0),
        )

    elif prov_to_test == "ollama":
        target_model = payload.model or settings.ollama_chat_model or "qwen2.5:1.5b"
        t0 = time.time()
        client = OllamaChatClient(default_model=target_model, settings=settings)
        server_health = client.check_server_health()
        elapsed = round(time.time() - t0, 3)

        if server_health.get("available"):
            model_avail = server_health.get("model_available", False)
            if model_avail:
                return TestLLMConnectionResponse(
                    provider="ollama",
                    model=target_model,
                    success=True,
                    connected=True,
                    status="connected",
                    message=f"Connected to local Ollama server ({settings.ollama_base_url}) and verified model '{target_model}'.",
                    elapsed_seconds=elapsed,
                )
            else:
                return TestLLMConnectionResponse(
                    provider="ollama",
                    model=target_model,
                    success=False,
                    connected=False,
                    status="unavailable",
                    message=f"Ollama server is running but model '{target_model}' was not found. Available: {', '.join(server_health.get('available_models', []))}",
                    elapsed_seconds=elapsed,
                )
        else:
            return TestLLMConnectionResponse(
                provider="ollama",
                model=target_model,
                success=False,
                connected=False,
                status="unavailable",
                message=f"Cannot reach Ollama server at {settings.ollama_base_url}: {server_health.get('error', 'Daemon offline')}",
                elapsed_seconds=elapsed,
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_PROVIDER",
                "message": f"Unsupported provider '{prov_to_test}'. Must be 'ollama' or 'nvidia'.",
            },
        )
