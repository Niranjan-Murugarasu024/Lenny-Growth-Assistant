from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Exception Hierarchy
# ============================================================================

class ProviderError(Exception):
    """Base exception for all chat model provider errors."""
    pass


class ProviderConfigError(ProviderError):
    """Raised when provider configuration or credentials are missing or invalid."""
    pass


class ProviderModelNotFoundError(ProviderError):
    """Raised when the configured chat model is not found or unavailable."""
    pass


class ProviderTimeoutError(ProviderError):
    """Raised when an inference or communication request times out."""
    pass


class ProviderConnectionError(ProviderError):
    """Raised when unable to connect to the model provider service."""
    pass


class ProviderAuthenticationError(ProviderError):
    """Raised when authentication with the provider fails (e.g. invalid API key)."""
    pass


class ProviderRateLimitError(ProviderError):
    """Raised when upstream rate limits or quota thresholds are exceeded."""
    pass


class ProviderResponseError(ProviderError):
    """Raised when the provider returns an empty, malformed, or invalid response."""
    pass


# ============================================================================
# Chat Provider Interface
# ============================================================================

class ChatProvider(ABC):
    """
    Abstract interface for chat model inference providers.

    Decouples RAG generation and health observability from specific LLM runtimes
    (e.g., local Ollama vs. cloud providers via LiteLLM).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g. 'ollama', 'litellm')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Configured model identifier."""
        pass

    @abstractmethod
    def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """
        Send a chat completion request and return normalized response metadata.

        Returns:
            dict containing:
                - 'content': str (non-empty assistant message text)
                - 'model': str (resolved or configured model identifier)
                - optional telemetry fields ('usage', 'total_duration_ns', etc.)
        """
        pass

    @abstractmethod
    def check_health(self) -> dict[str, Any]:
        """
        Perform a lightweight readiness or availability check.

        Must NOT generate billable completion tokens merely to test readiness.

        Returns:
            dict containing:
                - 'available': bool
                - 'status': str ('available', 'configured', 'unavailable', 'misconfigured')
                - 'model_available': bool
                - optional 'error': str
        """
        pass
