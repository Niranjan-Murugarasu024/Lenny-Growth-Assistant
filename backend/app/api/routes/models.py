from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.deps import get_app_settings
from backend.app.api.schemas import (
    ModelConfigResponse,
    ModelOptionInfo,
    ModelSwitchRequest,
)
from backend.app.config import Settings
from backend.app.rag.litellm_client import LiteLLMChatClient
from backend.app.rag.ollama_client import OllamaChatClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/config/models", tags=["Model Configuration"])


def _build_model_status(settings: Settings) -> ModelConfigResponse:
    """Construct current model configuration response without exposing sensitive keys."""
    # 1. Ollama status
    ollama_client = OllamaChatClient(settings=settings)
    ollama_health = ollama_client.check_server_health()
    ollama_available = ollama_health.get("available", False)
    ollama_status = "available" if ollama_available else "unavailable"
    ollama_msg = None if ollama_available else ollama_health.get("error", "Ollama daemon unreachable")

    # 2. LiteLLM (Cloud) status
    litellm_client = LiteLLMChatClient(settings=settings)
    litellm_health = litellm_client.check_health()
    if litellm_health.get("available"):
        litellm_status = "available"
    elif "LITELLM_API_KEY is missing" in (litellm_health.get("error") or ""):
        litellm_status = "unconfigured"
    else:
        litellm_status = "unavailable"
    litellm_msg = litellm_health.get("error")

    active_provider = (settings.chat_provider or "ollama").strip().lower()
    if active_provider == "ollama":
        active_model = settings.ollama_chat_model or "qwen2.5:1.5b"
        displayed_label = f"Ollama · {active_model}"
    else:
        active_model = settings.litellm_model or "openai/gpt-oss-20b"
        displayed_label = f"OpenAI · {active_model.replace('openai/', '')}"

    ollama_option = ModelOptionInfo(
        id="ollama/qwen2.5:1.5b",
        provider="ollama",
        model=settings.ollama_chat_model or "qwen2.5:1.5b",
        label=f"Ollama · {settings.ollama_chat_model or 'qwen2.5:1.5b'}",
        purpose="Mandatory local demo",
        status=ollama_status,
        status_message=ollama_msg,
        is_active=(active_provider == "ollama"),
    )

    cloud_model_id = settings.litellm_model or "openai/gpt-oss-20b"
    cloud_label = f"OpenAI · {cloud_model_id.replace('openai/', '')}"
    cloud_option = ModelOptionInfo(
        id=cloud_model_id,
        provider="litellm",
        model=cloud_model_id,
        label=cloud_label,
        purpose="Configurable cloud inference",
        status=litellm_status,
        status_message=litellm_msg,
        is_active=(active_provider in ("litellm", "cloud")),
    )

    return ModelConfigResponse(
        active_provider=active_provider,
        active_model=active_model,
        displayed_label=displayed_label,
        fallback_enabled=getattr(settings, "fallback_to_ollama", False),
        models=[ollama_option, cloud_option],
    )


@router.get("", response_model=ModelConfigResponse)
def get_model_config(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelConfigResponse:
    """Retrieve active LLM provider/model and all available options with operational health."""
    return _build_model_status(settings)


import dataclasses
from backend.app.config import Settings, set_active_settings

@router.post("/switch", response_model=ModelConfigResponse)
def switch_model_provider(
    payload: ModelSwitchRequest,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelConfigResponse:
    """
    Switch active inference provider and model dynamically without modifying code.
    Enforces security: does not allow activating cloud model if credentials are missing.
    """
    target_prov = payload.provider.strip().lower()

    if target_prov == "litellm":
        if not settings.litellm_api_key and not settings.litellm_api_base:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "MISSING_CLOUD_CREDENTIALS",
                    "message": "Cannot switch to cloud provider: LITELLM_API_KEY is not configured in environment.",
                },
            )
        new_model = payload.model if payload.model else (settings.litellm_model or "openai/gpt-oss-20b")
        updated_settings = dataclasses.replace(
            settings,
            chat_provider="litellm",
            litellm_model=new_model,
        )
        set_active_settings(updated_settings)
        logger.info("Switched active inference provider to LiteLLM (model=%s)", updated_settings.litellm_model)

    elif target_prov == "ollama":
        new_model = payload.model if payload.model else (settings.ollama_chat_model or "qwen2.5:1.5b")
        updated_settings = dataclasses.replace(
            settings,
            chat_provider="ollama",
            ollama_chat_model=new_model,
        )
        set_active_settings(updated_settings)
        logger.info("Switched active inference provider to Ollama (model=%s)", updated_settings.ollama_chat_model)

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_PROVIDER",
                "message": f"Unsupported provider '{payload.provider}'. Must be 'ollama' or 'litellm'.",
            },
        )

    return _build_model_status(updated_settings)
