from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.app.config import Settings, get_settings
from backend.app.rag.provider_base import (
    ChatProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderModelNotFoundError,
    ProviderResponseError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)


class OllamaClientError(ProviderError):
    """Base exception for Ollama chat client operations."""
    pass


class OllamaModelNotFoundError(OllamaClientError, ProviderModelNotFoundError):
    """Raised when the requested model is not installed or available on the Ollama server."""
    pass


class OllamaTimeoutError(OllamaClientError, ProviderTimeoutError):
    """Raised when an inference or health request to Ollama times out."""
    pass


class OllamaConnectionError(OllamaClientError, ProviderConnectionError):
    """Raised when the Ollama server cannot be reached."""
    pass


class OllamaChatClient(ChatProvider):
    """HTTP client for local Ollama chat model inference with health checks and error handling."""

    name: str = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout_seconds: float | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self.base_url = (base_url or cfg.ollama_base_url).rstrip("/")
        self.default_model = default_model or cfg.ollama_chat_model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else cfg.chat_timeout_seconds

    @property
    def name(self) -> str:
        """Provider name."""
        return "ollama"

    @property
    def model_name(self) -> str:
        """Configured default model."""
        return self.default_model

    def check_health(self) -> dict[str, Any]:
        """Perform a readiness health check against the local Ollama instance."""
        return self.check_server_health()

    def check_server_health(self) -> dict[str, Any]:
        """
        Check Ollama server availability and inspect installed models without generating text.
        """
        url = f"{self.base_url}/api/tags"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return {
                    "available": True,
                    "models": models,
                    "model_available": any(
                        m == self.default_model or m.startswith(f"{self.default_model}:")
                        for m in models
                    ),
                }
        except httpx.TimeoutException as exc:
            logger.warning("Ollama health check timed out: %s", exc)
            return {"available": False, "error": "timeout", "models": [], "model_available": False}
        except httpx.ConnectError as exc:
            logger.warning("Could not connect to Ollama server at %s: %s", self.base_url, exc)
            return {"available": False, "error": "connection_refused", "models": [], "model_available": False}
        except Exception as exc:
            logger.warning("Ollama health check failed: %s", exc)
            return {"available": False, "error": str(exc), "models": [], "model_available": False}

    def verify_model_available(self, model_name: str | None = None) -> bool:
        """Verify that the designated model is installed on Ollama."""
        target_model = model_name or self.default_model
        health = self.check_server_health()
        if not health["available"]:
            return False
        installed = health.get("models", [])
        return any(m == target_model or m.startswith(f"{target_model}:") for m in installed)

    def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """
        Send a chat completion request to the local Ollama instance.

        Enforces model verification, non-empty response validation, and timeout handling.
        """
        target_model = model or self.default_model

        # 1. Verify model is installed
        if not self.verify_model_available(target_model):
            raise OllamaModelNotFoundError(
                f"Configured chat model {target_model!r} is not installed or available on Ollama server at {self.base_url}. "
                f"Please ensure '{target_model}' is pulled."
            )

        # 2. Issue chat completion request
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": target_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_ctx": 4096,
            },
        }

        logger.info(
            "Sending chat request to Ollama model=%s (turns=%d, timeout=%.1fs)",
            target_model,
            len(messages),
            self.timeout_seconds,
        )

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()

            msg = data.get("message", {})
            content = msg.get("content", "").strip()

            if not content:
                done_reason = data.get("done_reason", "unknown")
                has_thinking = bool(msg.get("thinking"))
                logger.error(
                    "Ollama returned empty response content (done_reason=%s, has_thinking=%s, keys=%s)",
                    done_reason,
                    has_thinking,
                    list(data.keys()),
                )
                raise OllamaClientError(
                    f"Ollama returned empty response content for model {target_model!r} (done_reason: {done_reason})"
                )

            return {
                "content": content,
                "model": data.get("model", target_model),
                "total_duration_ns": data.get("total_duration"),
                "prompt_eval_count": data.get("prompt_eval_count"),
                "eval_count": data.get("eval_count"),
            }

        except httpx.TimeoutException as exc:
            logger.error("Ollama chat generation timed out after %.1fs", self.timeout_seconds)
            raise OllamaTimeoutError(
                f"Chat generation timed out after {self.timeout_seconds} seconds"
            ) from exc

        except httpx.ConnectError as exc:
            logger.error("Could not connect to Ollama at %s: %s", self.base_url, exc)
            raise OllamaConnectionError(
                f"Failed to connect to Ollama server at {self.base_url}"
            ) from exc

        except httpx.HTTPStatusError as exc:
            logger.error("Ollama HTTP status error %d: %s", exc.response.status_code, exc.response.text)
            raise OllamaClientError(
                f"Ollama returned HTTP error {exc.response.status_code}: {exc.response.text}"
            ) from exc

        except Exception as exc:
            if isinstance(exc, OllamaClientError):
                raise
            logger.error("Unexpected error during Ollama chat generation: %s", exc)
            raise OllamaClientError(f"Ollama generation failed: {exc}") from exc
