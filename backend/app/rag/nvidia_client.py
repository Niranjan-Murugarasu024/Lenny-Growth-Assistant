from __future__ import annotations

import logging
import time
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


class NvidiaChatClient(ChatProvider):
    """
    NVIDIA NIM cloud inference client using OpenAI-compatible SDK endpoint.

    Endpoint: https://integrate.api.nvidia.com/v1
    Model: openai/gpt-oss-20b
    """

    name: str = "nvidia"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        if model is not None:
            self.model = model.strip()
        else:
            self.model = (cfg.nvidia_model or "openai/gpt-oss-20b").strip()

        if base_url is not None:
            self.base_url = base_url.strip()
        else:
            self.base_url = (cfg.nvidia_base_url or "https://integrate.api.nvidia.com/v1").strip()

        if api_key is not None:
            self.api_key = api_key.strip() or None
        else:
            raw_key = cfg.nvidia_api_key or cfg.litellm_api_key or ""
            self.api_key = raw_key.strip() or None

        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else cfg.nvidia_timeout_seconds
        )

    @property
    def name(self) -> str:
        """Provider name."""
        return "nvidia"

    @property
    def model_name(self) -> str:
        """Configured cloud model identifier."""
        return self.model

    @property
    def client(self):
        """Lazy-loaded OpenAI-compatible client for NVIDIA NIM."""
        if not hasattr(self, "_openai_client") or self._openai_client is None:
            import openai
            self._openai_client = openai.OpenAI(
                base_url=self.base_url,
                api_key=self.api_key or "missing-key",
                timeout=self.timeout_seconds,
            )
        return self._openai_client

    @client.setter
    def client(self, value):
        self._openai_client = value

    def __repr__(self) -> str:
        masked = "***" if self.api_key else "None"
        return (
            f"<NvidiaChatClient(model={self.model!r}, "
            f"base_url={self.base_url!r}, "
            f"configured={bool(self.api_key)}, "
            f"api_key={masked})>"
        )

    def check_health(self) -> dict[str, Any]:
        """
        Lightweight configuration verification without issuing billable completion requests.

        Returns:
            dict containing available flag, configured flag, status ('not_configured' or 'configured'),
            and safe error message if unconfigured.
        """
        if not self.model:
            return {
                "available": False,
                "configured": False,
                "status": "not_configured",
                "model": "",
                "model_available": False,
                "error": "NVIDIA_MODEL is not configured. Set NVIDIA_MODEL in backend environment.",
            }

        if not self.api_key:
            return {
                "available": False,
                "configured": False,
                "status": "not_configured",
                "model": self.model,
                "model_available": False,
                "error": f"NVIDIA_API_KEY is not configured for model {self.model!r}.",
            }

        return {
            "available": True,
            "configured": True,
            "status": "configured",
            "model": self.model,
            "model_available": True,
            "error": None,
        }

    def test_connection(self) -> dict[str, Any]:
        """
        Explicit live connectivity and authorization test.
        Sends a minimal test completion request (max_tokens=5) to verify model availability.
        Never leaks API keys or internal tokens in response or logs.
        """
        health = self.check_health()
        if not health["available"]:
            return {
                "success": False,
                "connected": False,
                "status": "not_configured",
                "model": self.model,
                "message": health.get("error") or "Missing NVIDIA credentials.",
                "elapsed_seconds": 0.0,
            }

        try:
            import openai
        except ImportError as exc:
            return {
                "success": False,
                "connected": False,
                "status": "unavailable",
                "model": self.model,
                "message": f"openai package not installed: {exc}",
                "elapsed_seconds": 0.0,
            }

        t0 = time.time()
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Test connection"}],
                max_tokens=5,
            )
            elapsed = round(time.time() - t0, 3)
            return {
                "success": True,
                "connected": True,
                "status": "connected",
                "model": getattr(resp, "model", self.model) or self.model,
                "message": "Successfully connected to NVIDIA NIM endpoint.",
                "elapsed_seconds": elapsed,
            }
        except openai.AuthenticationError as exc:
            elapsed = round(time.time() - t0, 3)
            logger.warning("NVIDIA test connection rejected (authentication failed)")
            return {
                "success": False,
                "connected": False,
                "status": "unavailable",
                "model": self.model,
                "message": "Authentication failed: NVIDIA rejected API credentials.",
                "elapsed_seconds": elapsed,
            }
        except openai.RateLimitError as exc:
            elapsed = round(time.time() - t0, 3)
            logger.warning("NVIDIA test connection rejected (rate limit)")
            return {
                "success": False,
                "connected": False,
                "status": "unavailable",
                "model": self.model,
                "message": "Rate limit or quota exceeded on NVIDIA endpoint.",
                "elapsed_seconds": elapsed,
            }
        except openai.NotFoundError as exc:
            elapsed = round(time.time() - t0, 3)
            logger.warning("NVIDIA model %s not found upstream", self.model)
            return {
                "success": False,
                "connected": False,
                "status": "unavailable",
                "model": self.model,
                "message": f"Model {self.model!r} not found on NVIDIA endpoint.",
                "elapsed_seconds": elapsed,
            }
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            elapsed = round(time.time() - t0, 3)
            logger.warning("NVIDIA test connection failed: %s", exc)
            return {
                "success": False,
                "connected": False,
                "status": "unavailable",
                "model": self.model,
                "message": f"Could not connect to NVIDIA endpoint ({self.base_url}): request timed out or network error.",
                "elapsed_seconds": elapsed,
            }
        except Exception as exc:
            elapsed = round(time.time() - t0, 3)
            logger.warning("NVIDIA test connection error: %s", exc)
            return {
                "success": False,
                "connected": False,
                "status": "unavailable",
                "model": self.model,
                "message": f"NVIDIA provider error: {exc}",
                "elapsed_seconds": elapsed,
            }

    def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """
        Send a chat completion request to NVIDIA NIM and return normalized response text.
        Extracts assistant user-facing text without leaking internal reasoning or API metadata.
        """
        target_model = (model or self.model).strip()
        if not target_model:
            raise ProviderConfigError(
                "NVIDIA_MODEL is not configured. Set NVIDIA_MODEL in backend environment."
            )

        if not self.api_key:
            raise ProviderConfigError(
                f"NVIDIA_API_KEY is not configured for cloud model {target_model!r}."
            )

        try:
            import openai
        except ImportError as exc:
            raise ProviderConfigError(
                "The 'openai' package is required for NVIDIA NIM inference. Run 'pip install openai'."
            ) from exc

        logger.info(
            "Dispatching NVIDIA NIM chat request (model=%s, turns=%d, timeout=%.1fs)",
            target_model,
            len(messages),
            self.timeout_seconds,
        )

        try:
            resp = self.client.chat.completions.create(
                model=target_model,
                messages=messages,
                temperature=temperature,
            )

            choices = getattr(resp, "choices", [])
            if not choices:
                raise ProviderResponseError(
                    f"NVIDIA NIM returned empty choices for model {target_model!r}"
                )

            msg = choices[0].message
            content = (getattr(msg, "content", None) or "").strip()

            if not content:
                raise ProviderResponseError(
                    f"NVIDIA NIM returned empty message content for model {target_model!r}"
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

        except openai.AuthenticationError as exc:
            logger.error("Authentication failed for NVIDIA model %s (API key rejected)", target_model)
            raise ProviderAuthenticationError(
                f"Authentication failed for cloud provider model {target_model!r}. Check your NVIDIA API credentials."
            ) from exc

        except openai.RateLimitError as exc:
            logger.error("Rate limit or quota exceeded for NVIDIA model %s", target_model)
            raise ProviderRateLimitError(
                f"Rate limit or quota exceeded for cloud model {target_model!r}."
            ) from exc

        except openai.NotFoundError as exc:
            logger.error("Configured NVIDIA model %s was not found upstream", target_model)
            raise ProviderModelNotFoundError(
                f"Cloud model {target_model!r} not found on NVIDIA NIM endpoint."
            ) from exc

        except openai.APITimeoutError as exc:
            logger.error("NVIDIA request timed out for model %s after %.1fs", target_model, self.timeout_seconds)
            raise ProviderTimeoutError(
                f"Cloud model generation timed out after {self.timeout_seconds}s for model {target_model!r}."
            ) from exc

        except openai.APIConnectionError as exc:
            logger.error("Could not connect to NVIDIA endpoint for model %s", target_model)
            raise ProviderConnectionError(
                f"Failed to connect to cloud provider endpoint for model {target_model!r}."
            ) from exc

        except openai.BadRequestError as exc:
            logger.error("Bad request to NVIDIA endpoint for model %s: %s", target_model, exc)
            raise ProviderError(
                f"Invalid request rejected by cloud provider for model {target_model!r}: {exc}"
            ) from exc

        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            logger.error("Unexpected error during NVIDIA generation: %s", exc)
            raise ProviderError(
                f"NVIDIA NIM inference failed for model {target_model!r}: {exc}"
            ) from exc
