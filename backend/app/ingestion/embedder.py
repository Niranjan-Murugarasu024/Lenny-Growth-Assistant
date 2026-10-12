from __future__ import annotations

import logging
import math
import time
from typing import Any

import httpx

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Base exception for embedding failures."""


class EmbeddingConnectionError(EmbeddingError):
    """Raised when Ollama connection or network request fails after retries."""


class EmbeddingBatchCountError(EmbeddingError):
    """Raised when the number of returned embeddings does not match the input batch count."""


class EmbeddingDimensionError(EmbeddingError):
    """Raised when a returned embedding vector has an unexpected dimension."""


class EmbeddingValueError(EmbeddingError):
    """Raised when an embedding contains non-finite or invalid numeric values."""


class EmbeddingOversizedInputError(EmbeddingError):
    """Raised when Ollama rejects an input that exceeds the model's context window with truncate=false."""


class OllamaEmbedder:
    """Client for generating document and query embeddings via Ollama /api/embed."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        batch_size: int | None = None,
        dimensions: int | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.embedding_model
        self.batch_size = batch_size if batch_size is not None else settings.embed_batch_size
        self.dimensions = dimensions if dimensions is not None else settings.embedding_dimensions
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._custom_client = client

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(timeout=self.timeout_seconds)

    def _validate_vector(self, vector: Any, batch_idx: int, item_idx: int) -> list[float]:
        """Validate that a returned vector has exact dimensions and finite float values."""
        if not isinstance(vector, (list, tuple)):
            raise EmbeddingValueError(
                f"Item {item_idx} in batch {batch_idx}: expected list of floats, got {type(vector).__name__}"
            )

        if len(vector) != self.dimensions:
            raise EmbeddingDimensionError(
                f"Item {item_idx} in batch {batch_idx}: expected dimension {self.dimensions}, got {len(vector)}"
            )

        validated: list[float] = []
        for val_idx, val in enumerate(vector):
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise EmbeddingValueError(
                    f"Item {item_idx} in batch {batch_idx} (element {val_idx}): non-numeric value {val!r}"
                )
            f_val = float(val)
            if not math.isfinite(f_val):
                raise EmbeddingValueError(
                    f"Item {item_idx} in batch {batch_idx} (element {val_idx}): non-finite value {val!r}"
                )
            validated.append(f_val)

        return validated

    def _post_batch_with_retry(
        self,
        client: httpx.Client,
        endpoint: str,
        payload: dict[str, Any],
        batch_idx: int,
        batch_size: int,
    ) -> dict[str, Any]:
        """Post an embedding batch to Ollama with bounded exponential backoff retries."""
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = client.post(endpoint, json=payload)

                # Check for context window / oversized input errors (often 400 with message)
                if response.status_code == 400:
                    try:
                        err_data = response.json()
                        err_msg = str(err_data.get("error", ""))
                    except Exception:
                        err_msg = response.text
                    if "context length" in err_msg.lower() or "truncate" in err_msg.lower():
                        raise EmbeddingOversizedInputError(
                            f"Batch {batch_idx} rejected by Ollama: input exceeds context length ({err_msg})"
                        )
                    raise EmbeddingError(
                        f"Ollama bad request (400) for batch {batch_idx}: {err_msg}"
                    )

                # Retry on 5xx or 429
                if response.status_code in (429, 500, 502, 503, 504):
                    err_msg = f"HTTP {response.status_code}"
                    logger.warning(
                        "Ollama returned %s for batch %d (attempt %d/%d)",
                        err_msg,
                        batch_idx,
                        attempt,
                        self.max_retries,
                    )
                    last_error = EmbeddingConnectionError(
                        f"Ollama server returned {response.status_code} on attempt {attempt}"
                    )
                    if attempt < self.max_retries:
                        time.sleep(0.5 * (2 ** (attempt - 1)))
                        continue
                    raise last_error

                response.raise_for_status()
                return response.json()

            except (httpx.TransportError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Network error connecting to Ollama for batch %d (attempt %d/%d): %s",
                    batch_idx,
                    attempt,
                    self.max_retries,
                    exc,
                )
                last_error = EmbeddingConnectionError(
                    f"Failed to connect to Ollama at {self.base_url}: {exc}"
                )
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                raise last_error from exc

        if last_error:
            raise last_error
        raise EmbeddingConnectionError("Failed to receive response from Ollama")

    def embed_documents(
        self,
        texts: list[str],
        prefix: str = "search_document: ",
    ) -> list[list[float]]:
        """
        Embed a list of document chunk texts using Ollama /api/embed.

        Prefixes each document with 'search_document: ' without mutating the stored text.
        Sends inputs in batches with truncate=false and validates all returned dimensions.
        """
        if not texts:
            return []

        endpoint = f"{self.base_url}/api/embed"
        all_embeddings: list[list[float]] = []
        client = self._get_client()

        should_close_client = self._custom_client is None

        try:
            total_items = len(texts)
            num_batches = math.ceil(total_items / self.batch_size)

            for b_idx in range(num_batches):
                start = b_idx * self.batch_size
                end = min(start + self.batch_size, total_items)
                batch_slice = texts[start:end]

                # Prepend task prefix to each text for embedding only
                prefixed_inputs = [f"{prefix}{t}" for t in batch_slice]

                payload = {
                    "model": self.model,
                    "input": prefixed_inputs,
                    "truncate": False,
                }

                logger.debug(
                    "Embedding batch %d/%d (%d texts, avg char length: %.1f)",
                    b_idx + 1,
                    num_batches,
                    len(batch_slice),
                    sum(len(t) for t in batch_slice) / len(batch_slice) if batch_slice else 0.0,
                )

                resp_data = self._post_batch_with_retry(
                    client=client,
                    endpoint=endpoint,
                    payload=payload,
                    batch_idx=b_idx + 1,
                    batch_size=len(batch_slice),
                )

                raw_embeddings = resp_data.get("embeddings")
                if not isinstance(raw_embeddings, list):
                    raise EmbeddingError(
                        f"Batch {b_idx + 1}: expected 'embeddings' list in Ollama response, got {type(raw_embeddings).__name__}"
                    )

                if len(raw_embeddings) != len(batch_slice):
                    raise EmbeddingBatchCountError(
                        f"Batch {b_idx + 1}: expected {len(batch_slice)} embeddings, received {len(raw_embeddings)}"
                    )

                # Validate dimensions and numerical finite values
                for item_idx, vec in enumerate(raw_embeddings):
                    validated_vec = self._validate_vector(vec, b_idx + 1, item_idx)
                    all_embeddings.append(validated_vec)

        finally:
            if should_close_client:
                client.close()

        return all_embeddings

    def embed_query(
        self,
        query: str,
        prefix: str = "search_query: ",
    ) -> list[float]:
        """
        Embed a single search query text using Ollama /api/embed with 'search_query: ' prefix.
        """
        results = self.embed_documents([query], prefix=prefix)
        if not results:
            raise EmbeddingError("No embedding returned for query")
        return results[0]
