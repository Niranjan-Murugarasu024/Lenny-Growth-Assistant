from __future__ import annotations

import logging
from typing import Any
import httpx

from backend.app.config import Settings, get_settings
from backend.app.rag.provider_base import (
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)


class PiAgentClient:
    """Client for communicating with the external Node.js Pi Coding Agent service."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = f"http://{self.settings.pi_agent_host}:{self.settings.pi_agent_port}"
        self.timeout_seconds = self.settings.pi_agent_request_timeout_seconds

    def check_health(self) -> dict[str, Any]:
        """Check liveness of the external Pi agent service."""
        url = f"{self.base_url}/health/live"
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Health check timed out connecting to Pi agent service at {url}"
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderConnectionError(
                f"Failed to connect to Pi agent service at {url}: {exc}"
            ) from exc

    def run_agent(
        self,
        question: str,
        conversation_history: list[dict[str, str]] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute an autonomous agent cycle via the Pi agent service.

        Returns a dictionary containing content, provider, model, sources,
        and execution metrics.
        """
        url = f"{self.base_url}/v1/agent/run"
        payload = {
            "question": question,
            "history": conversation_history or [],
            "request_id": request_id,
        }

        logger.info(
            "Calling Pi agent service at %s for request_id=%s (question length=%d)",
            url,
            request_id,
            len(question),
        )

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Pi agent inference timed out after {self.timeout_seconds:.1f}s."
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderConnectionError(
                f"Could not connect to Pi agent service at {url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            error_msg = f"Pi agent service returned HTTP {resp.status_code}: {resp.text}"
            logger.error("Pi agent failed for request_id=%s: %s", request_id, error_msg)
            raise ProviderError(error_msg)

        data = resp.json()
        logger.info(
            "Pi agent completed for request_id=%s: provider=%s, model=%s, sources=%d, elapsed=%.2fs",
            request_id,
            data.get("provider"),
            data.get("model"),
            len(data.get("sources", [])),
            data.get("elapsed_seconds", 0.0),
        )

        return data
