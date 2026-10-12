from __future__ import annotations

import logging
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.rag.provider_base import (
    ChatProvider,
    ProviderAuthenticationError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)


class LiteLLMChatClient(ChatProvider):
    """
    Cloud chat inference client backed by the LiteLLM SDK.

    Supports OpenAI, Anthropic, NVIDIA NIM, OpenRouter, and other providers
    via configurable model prefixes (e.g. 'openai/gpt-4o', 'nvidia_nim/...').
    """

    name: str = "litellm"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout_seconds: float | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        if model is not None:
            self.model = model.strip()
        else:
            self.model = (cfg.litellm_model or "openai/gpt-oss-20b").strip()
        if api_key is not None:
            self.api_key = api_key.strip() or None
        else:
            self.api_key = (cfg.litellm_api_key or "").strip() or None

        if api_base is not None:
            self.api_base = api_base.strip() or None
        else:
            self.api_base = (cfg.litellm_api_base or "").strip() or None
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else cfg.litellm_timeout_seconds
        )

    @property
    def name(self) -> str:
        """Provider name."""
        return "litellm"

    @property
    def model_name(self) -> str:
        """Configured cloud model identifier."""
        return self.model

    def check_health(self) -> dict[str, Any]:
        """
        Lightweight readiness check for cloud inference.

        Validates configuration and credential presence without issuing
        billable completion requests.
        """
        if not self.model:
            return {
                "available": False,
                "status": "misconfigured",
                "model": "",
                "model_available": False,
                "error": "LITELLM_MODEL is not configured. Set LITELLM_MODEL to a valid model identifier.",
            }

        # Check for presence of credentials (unless using an explicitly keyless endpoint)
        if not self.api_key and not self.api_base:
            return {
                "available": False,
                "status": "misconfigured",
                "model": self.model,
                "model_available": False,
                "error": f"LITELLM_API_KEY is missing for cloud model {self.model!r}.",
            }

        return {
            "available": True,
            "status": "configured",
            "model": self.model,
            "model_available": True,
        }

    def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """
        Send a completion request via LiteLLM and return normalized response text.

        Enforces non-empty content validation, timeout translation, and safe error logging.
        Never logs API keys, headers, or full prompt contents.
        """
        target_model = (model or self.model).strip()
        if not target_model:
            raise ProviderConfigError(
                "LITELLM_MODEL is not configured. Please set LITELLM_MODEL in environment configuration."
            )

        if not self.api_key and not self.api_base:
            raise ProviderConfigError(
                f"LITELLM_API_KEY is not configured for cloud model {target_model!r}."
            )

        # Lazy import of litellm to avoid startup penalty when running purely on local Ollama
        try:
            import litellm
            import litellm.exceptions
        except ImportError as exc:
            raise ProviderConfigError(
                "The 'litellm' package is not installed. Run 'pip install litellm' to enable cloud inference."
            ) from exc

        # Suppress litellm noisy telemetry / console prints
        litellm.telemetry = False
        litellm.suppress_debug_info = True

        call_kwargs: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "timeout": self.timeout_seconds,
        }
        if self.api_key:
            call_kwargs["api_key"] = self.api_key
        if self.api_base:
            call_kwargs["api_base"] = self.api_base

        logger.info(
            "Dispatching LiteLLM chat request (model=%s, turns=%d, timeout=%.1fs)",
            target_model,
            len(messages),
            self.timeout_seconds,
        )

        try:
            resp = litellm.completion(**call_kwargs)

            choices = getattr(resp, "choices", [])
            if not choices:
                raise ProviderResponseError(
                    f"LiteLLM returned empty choices for model {target_model!r}"
                )

            msg = choices[0].message
            content = (getattr(msg, "content", None) or "").strip()

            if not content:
                raise ProviderResponseError(
                    f"LiteLLM returned empty message content for model {target_model!r}"
                )

            resolved_model = getattr(resp, "model", None) or target_model
            usage_data: dict[str, Any] = {}
            if getattr(resp, "usage", None):
                usage = resp.usage
                usage_data = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }

            return {
                "content": content,
                "model": resolved_model,
                "usage": usage_data,
            }

        except litellm.exceptions.AuthenticationError as exc:
            logger.error("Authentication failed for LiteLLM model %s (API key rejected)", target_model)
            raise ProviderAuthenticationError(
                f"Authentication failed for cloud provider model {target_model!r}. Check your API credentials."
            ) from exc

        except litellm.exceptions.Timeout as exc:
            logger.error("LiteLLM request timed out for model %s after %.1fs", target_model, self.timeout_seconds)
            raise ProviderTimeoutError(
                f"Cloud model generation timed out after {self.timeout_seconds}s for model {target_model!r}"
            ) from exc

        except litellm.exceptions.RateLimitError as exc:
            logger.error("Rate limit or quota exceeded for LiteLLM model %s", target_model)
            raise ProviderRateLimitError(
                f"Rate limit or quota exceeded for cloud model {target_model!r}."
            ) from exc

        except litellm.exceptions.NotFoundError as exc:
            logger.error("Configured LiteLLM model %s was not found upstream", target_model)
            raise ProviderModelNotFoundError(
                f"Cloud model {target_model!r} not found on provider endpoint."
            ) from exc

        except litellm.exceptions.APIConnectionError as exc:
            logger.error("Could not connect to LiteLLM endpoint for model %s", target_model)
            raise ProviderConnectionError(
                f"Failed to connect to cloud provider endpoint for model {target_model!r}."
            ) from exc

        except litellm.exceptions.BadRequestError as exc:
            logger.error("Bad request to LiteLLM endpoint for model %s: %s", target_model, exc)
            raise ProviderError(
                f"Invalid request rejected by cloud provider for model {target_model!r}: {exc}"
            ) from exc

        except litellm.exceptions.APIError as exc:
            logger.error("Upstream API error from LiteLLM model %s: %s", target_model, exc)
            raise ProviderError(
                f"Upstream cloud provider error for model {target_model!r}: {exc}"
            ) from exc

        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            logger.error("Unexpected error during LiteLLM generation: %s", exc)
            raise ProviderError(
                f"LiteLLM inference failed for model {target_model!r}: {exc}"
            ) from exc
