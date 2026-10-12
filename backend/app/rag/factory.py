from __future__ import annotations

import logging

from backend.app.config import Settings, get_settings
from backend.app.rag.litellm_client import LiteLLMChatClient
from backend.app.rag.nvidia_client import NvidiaChatClient
from backend.app.rag.ollama_client import OllamaChatClient
from backend.app.rag.provider_base import ChatProvider, ProviderConfigError

logger = logging.getLogger(__name__)


def get_chat_provider(settings: Settings | None = None) -> ChatProvider:
    """
    Central factory function to instantiate the configured chat model inference provider.

    Defaults to local Ollama (qwen2.5:1.5b).
    Switches to NvidiaChatClient when CHAT_PROVIDER='nvidia' or 'nim'.
    Switches to LiteLLM when CHAT_PROVIDER='litellm' or 'cloud'.
    """
    cfg = settings or get_settings()
    provider_key = (cfg.chat_provider or "ollama").strip().lower()

    if provider_key == "ollama":
        logger.debug("Instantiating OllamaChatClient (model=%s)", cfg.ollama_chat_model)
        return OllamaChatClient(settings=cfg)
    elif provider_key in ("nvidia", "nim"):
        logger.debug("Instantiating NvidiaChatClient (model=%s)", cfg.nvidia_model)
        return NvidiaChatClient(settings=cfg)
    elif provider_key in ("litellm", "cloud"):
        if cfg.nvidia_api_key and not cfg.litellm_api_key:
            logger.debug("Instantiating NvidiaChatClient for cloud key (model=%s)", cfg.nvidia_model)
            return NvidiaChatClient(settings=cfg)
        logger.debug("Instantiating LiteLLMChatClient (model=%s)", cfg.litellm_model)
        return LiteLLMChatClient(settings=cfg)
    else:
        raise ProviderConfigError(
            f"Unsupported chat provider: {cfg.chat_provider!r}. "
            f"Supported providers are 'ollama' and 'nvidia'."
        )
