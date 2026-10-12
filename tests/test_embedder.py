from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.ingestion.embedder import (
    EmbeddingBatchCountError,
    EmbeddingConnectionError,
    EmbeddingDimensionError,
    EmbeddingOversizedInputError,
    EmbeddingValueError,
    OllamaEmbedder,
)


def _make_dummy_vector(dim: int = 768, val: float = 0.05) -> list[float]:
    return [val] * dim


def test_embed_documents_empty_list() -> None:
    embedder = OllamaEmbedder(base_url="http://localhost:11434")
    assert embedder.embed_documents([]) == []


def test_embed_documents_success_with_mocked_http() -> None:
    texts = ["First chunk of text", "Second chunk of text"]
    mock_embeddings = [_make_dummy_vector(768, 0.1), _make_dummy_vector(768, 0.2)]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"embeddings": mock_embeddings}

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_response

    embedder = OllamaEmbedder(
        base_url="http://localhost:11434",
        model="nomic-embed-text:v1.5",
        dimensions=768,
        batch_size=16,
        client=mock_client,
    )

    results = embedder.embed_documents(texts)

    assert len(results) == 2
    assert len(results[0]) == 768
    assert results[0][0] == 0.1
    assert len(results[1]) == 768
    assert results[1][0] == 0.2

    # Verify endpoint and payload
    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "http://localhost:11434/api/embed"
    payload = kwargs["json"]
    assert payload["model"] == "nomic-embed-text:v1.5"
    assert payload["truncate"] is False
    # Check that search_document: prefix was applied
    assert payload["input"] == [
        "search_document: First chunk of text",
        "search_document: Second chunk of text",
    ]


def test_embed_documents_batching_logic() -> None:
    texts = [f"Text chunk number {i}" for i in range(35)]
    batch_size = 16

    mock_client = MagicMock(spec=httpx.Client)

    def side_effect_post(url, json):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        count = len(json["input"])
        resp.json.return_value = {"embeddings": [_make_dummy_vector(768)] * count}
        return resp

    mock_client.post.side_effect = side_effect_post

    embedder = OllamaEmbedder(
        base_url="http://localhost:11434",
        batch_size=batch_size,
        client=mock_client,
    )

    results = embedder.embed_documents(texts)

    assert len(results) == 35
    assert mock_client.post.call_count == 3  # 16 + 16 + 3 = 35


def test_embed_documents_rejects_count_mismatch() -> None:
    texts = ["Chunk 1", "Chunk 2"]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    # Ollama returns only 1 embedding instead of 2
    mock_response.json.return_value = {"embeddings": [_make_dummy_vector(768)]}

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_response

    embedder = OllamaEmbedder(client=mock_client)

    with pytest.raises(EmbeddingBatchCountError, match="expected 2 embeddings, received 1"):
        embedder.embed_documents(texts)


def test_embed_documents_rejects_dimension_mismatch() -> None:
    texts = ["Chunk 1"]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    # Returns 512 dimensions instead of 768
    mock_response.json.return_value = {"embeddings": [_make_dummy_vector(512)]}

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_response

    embedder = OllamaEmbedder(dimensions=768, client=mock_client)

    with pytest.raises(EmbeddingDimensionError, match="expected dimension 768, got 512"):
        embedder.embed_documents(texts)


def test_embed_documents_rejects_non_finite_values() -> None:
    texts = ["Chunk 1"]

    bad_vector = _make_dummy_vector(768)
    bad_vector[10] = float("nan")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"embeddings": [bad_vector]}

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_response

    embedder = OllamaEmbedder(client=mock_client)

    with pytest.raises(EmbeddingValueError, match="non-finite value"):
        embedder.embed_documents(texts)


def test_embed_documents_handles_oversized_input_error() -> None:
    texts = ["Massive text exceeding context window"]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": "input exceeds context length"}

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_response

    embedder = OllamaEmbedder(client=mock_client)

    with pytest.raises(EmbeddingOversizedInputError, match="exceeds context length"):
        embedder.embed_documents(texts)


def test_embed_documents_retries_on_server_error() -> None:
    texts = ["Chunk text"]

    fail_response = MagicMock(spec=httpx.Response)
    fail_response.status_code = 503

    ok_response = MagicMock(spec=httpx.Response)
    ok_response.status_code = 200
    ok_response.json.return_value = {"embeddings": [_make_dummy_vector(768)]}

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = [fail_response, ok_response]

    embedder = OllamaEmbedder(max_retries=2, client=mock_client)

    with patch("time.sleep"):  # avoid waiting in unit tests
        results = embedder.embed_documents(texts)

    assert len(results) == 1
    assert mock_client.post.call_count == 2


def test_embed_query_applies_query_prefix() -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"embeddings": [_make_dummy_vector(768, 0.42)]}

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_response

    embedder = OllamaEmbedder(client=mock_client)
    res = embedder.embed_query("How to grow B2B SaaS?")

    assert len(res) == 768
    assert res[0] == 0.42

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["input"] == ["search_query: How to grow B2B SaaS?"]
