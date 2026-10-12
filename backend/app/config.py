from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Locate project root and load .env if present
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

if ENV_PATH.is_file():
    load_dotenv(dotenv_path=ENV_PATH, override=False)
else:
    load_dotenv(override=False)


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    database_url: str
    embedding_model: str = "nomic-embed-text:v1.5"
    embedding_dimensions: int = 768
    chunk_target_tokens: int = 450
    chunk_overlap_tokens: int = 60
    embed_batch_size: int = 16
    ollama_base_url: str = "http://localhost:11434"
    postgres_db: str | None = None
    postgres_user: str | None = None
    chat_provider: str = "ollama"
    ollama_chat_model: str = "qwen2.5:1.5b"
    chat_timeout_seconds: float = 120.0
    retrieval_top_k: int = 5
    retrieval_max_cosine_distance: float = 0.30
    chat_max_history_messages: int = 10
    litellm_model: str | None = None
    litellm_api_key: str | None = None
    litellm_api_base: str | None = None
    litellm_timeout_seconds: float = 120.0
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "openai/gpt-oss-20b"
    nvidia_api_key: str | None = None
    nvidia_timeout_seconds: float = 120.0
    chat_orchestrator: str = "rag"
    agent_internal_token: str = "lenny-agent-internal-secret-token"
    pi_agent_host: str = "127.0.0.1"
    pi_agent_port: int = 3000
    pi_agent_request_timeout_seconds: float = 240.0
    pi_agent_model_provider: str = "ollama"
    pi_agent_model_id: str = "qwen2.5:1.5b"
    pi_agent_model_base_url: str = "http://localhost:11434/v1"
    pi_agent_model_api_key: str = ""
    writing_target_word_count: int = 1250
    writing_timeout_seconds: float = 300.0
    redis_url: str = "redis://127.0.0.1:6379/0"
    worker_concurrency: int = 2
    worker_job_timeout_seconds: float = 360.0
    retrieval_mode: str = "hybrid"
    worker_stale_job_timeout_seconds: float = 300.0
    max_job_retries: int = 2
    fallback_to_ollama: bool = False

    def __post_init__(self) -> None:
        if not self.database_url or not self.database_url.strip():
            raise ValueError("DATABASE_URL must be set and non-empty.")

        if self.embedding_dimensions <= 0:
            raise ValueError(
                f"EMBEDDING_DIMENSIONS must be positive, got {self.embedding_dimensions}"
            )

        if self.chat_orchestrator not in {"rag", "pi"}:
            raise ValueError(
                f"CHAT_ORCHESTRATOR must be 'rag' or 'pi', got {self.chat_orchestrator!r}"
            )

        # Normalize dialect to postgresql+psycopg if postgresql:// provided
        normalized_url = self.database_url.strip()
        if normalized_url.startswith("postgresql://"):
            normalized_url = "postgresql+psycopg://" + normalized_url[len("postgresql://"):]
        elif not (
            normalized_url.startswith("postgresql+psycopg://")
            or normalized_url.startswith("sqlite")
        ):
            raise ValueError(
                "DATABASE_URL must use 'postgresql+psycopg://' or 'postgresql://' scheme."
            )

        object.__setattr__(self, "database_url", normalized_url)

    def sanitized_database_url(self) -> str:
        """Return DATABASE_URL with user password masked for safe logging."""
        # Regex to mask :password@ in URL
        return re.sub(
            r":([^:@]+)@",
            ":***@",
            self.database_url,
        )

    def sanitized_litellm_api_key(self) -> str | None:
        """Return masked LiteLLM API key for safe logging."""
        if not self.litellm_api_key:
            return None
        key = self.litellm_api_key.strip()
        if len(key) <= 8:
            return "***"
        return f"{key[:3]}...{key[-4:]}"

    def sanitized_nvidia_api_key(self) -> str | None:
        """Return masked NVIDIA API key for safe logging."""
        if not self.nvidia_api_key:
            return None
        key = self.nvidia_api_key.strip()
        if len(key) <= 8:
            return "***"
        return f"{key[:3]}...{key[-4:]}"

    def __repr__(self) -> str:
        return (
            f"Settings(database_url={self.sanitized_database_url()!r}, "
            f"embedding_model={self.embedding_model!r}, "
            f"embedding_dimensions={self.embedding_dimensions}, "
            f"chunk_target_tokens={self.chunk_target_tokens}, "
            f"chunk_overlap_tokens={self.chunk_overlap_tokens}, "
            f"embed_batch_size={self.embed_batch_size}, "
            f"ollama_base_url={self.ollama_base_url!r}, "
            f"chat_provider={self.chat_provider!r}, "
            f"chat_orchestrator={self.chat_orchestrator!r}, "
            f"ollama_chat_model={self.ollama_chat_model!r}, "
            f"nvidia_model={self.nvidia_model!r}, "
            f"nvidia_api_key={'***' if self.nvidia_api_key else None!r}, "
            f"litellm_model={self.litellm_model!r}, "
            f"litellm_api_key={'***' if self.litellm_api_key else None!r})"
        )


def load_settings(
    env_file: Path | str | None = None,
    **overrides: object,
) -> Settings:
    """Load settings from environment variables or custom overrides."""
    if env_file:
        load_dotenv(dotenv_path=Path(env_file), override=True)

    db_url = overrides.get("database_url") or os.getenv("DATABASE_URL", "")
    if not isinstance(db_url, str):
        db_url = str(db_url)

    emb_model = str(
        overrides.get("embedding_model")
        or os.getenv("EMBEDDING_MODEL", "nomic-embed-text:v1.5")
    )

    emb_dims_raw = overrides.get("embedding_dimensions") or os.getenv(
        "EMBEDDING_DIMENSIONS", "768"
    )
    emb_dims = int(emb_dims_raw)

    target_tokens_raw = overrides.get("chunk_target_tokens") or os.getenv(
        "CHUNK_TARGET_TOKENS", "450"
    )
    target_tokens = int(target_tokens_raw)

    overlap_tokens_raw = overrides.get("chunk_overlap_tokens") or os.getenv(
        "CHUNK_OVERLAP_TOKENS", "60"
    )
    overlap_tokens = int(overlap_tokens_raw)

    batch_size_raw = overrides.get("embed_batch_size") or os.getenv(
        "EMBED_BATCH_SIZE", "16"
    )
    batch_size = int(batch_size_raw)

    ollama_url = str(
        overrides.get("ollama_base_url")
        or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )

    pg_db = overrides.get("postgres_db") or os.getenv("POSTGRES_DB")
    pg_user = overrides.get("postgres_user") or os.getenv("POSTGRES_USER")

    chat_prov = str(
        overrides.get("chat_provider")
        or os.getenv("CHAT_PROVIDER", "ollama")
    )
    chat_mod = str(
        overrides.get("ollama_chat_model")
        or os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:1.5b")
    )
    chat_to_raw = overrides.get("chat_timeout_seconds") or os.getenv(
        "CHAT_TIMEOUT_SECONDS", "120.0"
    )
    chat_timeout = float(chat_to_raw)

    ret_top_k_raw = overrides.get("retrieval_top_k") or os.getenv(
        "RETRIEVAL_TOP_K", "5"
    )
    ret_top_k = int(ret_top_k_raw)

    ret_max_dist_raw = overrides.get("retrieval_max_cosine_distance") or os.getenv(
        "RETRIEVAL_MAX_COSINE_DISTANCE", "0.30"
    )
    ret_max_dist = float(ret_max_dist_raw)

    chat_hist_raw = overrides.get("chat_max_history_messages") or os.getenv(
        "CHAT_MAX_HISTORY_MESSAGES", "10"
    )
    chat_hist = int(chat_hist_raw)

    litellm_mod = overrides.get("litellm_model") or os.getenv("LITELLM_MODEL")
    litellm_key = overrides.get("litellm_api_key") or os.getenv("LITELLM_API_KEY")
    litellm_base = overrides.get("litellm_api_base") or os.getenv("LITELLM_API_BASE")
    litellm_to_raw = overrides.get("litellm_timeout_seconds") or os.getenv(
        "LITELLM_TIMEOUT_SECONDS", str(chat_timeout)
    )
    litellm_timeout = float(litellm_to_raw)

    nvidia_base = str(
        overrides.get("nvidia_base_url")
        or os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    )
    nvidia_mod = str(
        overrides.get("nvidia_model")
        or os.getenv("NVIDIA_MODEL", "openai/gpt-oss-20b")
    )
    nvidia_key = overrides.get("nvidia_api_key") or os.getenv("NVIDIA_API_KEY")
    nvidia_to_raw = overrides.get("nvidia_timeout_seconds") or os.getenv(
        "NVIDIA_TIMEOUT_SECONDS", str(chat_timeout)
    )
    nvidia_timeout = float(nvidia_to_raw)

    chat_orch = str(
        overrides.get("chat_orchestrator")
        or os.getenv("CHAT_ORCHESTRATOR", "rag")
    ).lower()
    agent_tok = str(
        overrides.get("agent_internal_token")
        or os.getenv("AGENT_INTERNAL_TOKEN", "lenny-agent-internal-secret-token")
    )
    pi_host = str(
        overrides.get("pi_agent_host")
        or os.getenv("PI_AGENT_HOST", "127.0.0.1")
    )
    pi_port_raw = overrides.get("pi_agent_port") or os.getenv("PI_AGENT_PORT", "3000")
    pi_port = int(pi_port_raw)
    pi_timeout_raw = overrides.get("pi_agent_request_timeout_seconds") or os.getenv(
        "PI_AGENT_REQUEST_TIMEOUT_SECONDS", "240.0"
    )
    pi_timeout = float(pi_timeout_raw)
    pi_provider = str(
        overrides.get("pi_agent_model_provider")
        or os.getenv("PI_AGENT_MODEL_PROVIDER", "ollama")
    )
    pi_model_id = str(
        overrides.get("pi_agent_model_id")
        or os.getenv("PI_AGENT_MODEL_ID", "qwen2.5:1.5b")
    )
    pi_base_url = str(
        overrides.get("pi_agent_model_base_url")
        or os.getenv("PI_AGENT_MODEL_BASE_URL", "http://localhost:11434/v1")
    )
    pi_api_key = str(
        overrides.get("pi_agent_model_api_key")
        or os.getenv("PI_AGENT_MODEL_API_KEY", "")
    )

    writing_words_raw = overrides.get("writing_target_word_count") or os.getenv(
        "WRITING_TARGET_WORD_COUNT", "1250"
    )
    writing_words = int(writing_words_raw)

    writing_to_raw = overrides.get("writing_timeout_seconds") or os.getenv(
        "WRITING_TIMEOUT_SECONDS", "300.0"
    )
    writing_timeout = float(writing_to_raw)

    redis_conn_url = str(
        overrides.get("redis_url") or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    worker_conc_raw = overrides.get("worker_concurrency") or os.getenv(
        "WORKER_CONCURRENCY", "2"
    )
    worker_concurrency = int(worker_conc_raw)

    worker_job_to_raw = overrides.get("worker_job_timeout_seconds") or os.getenv(
        "WORKER_JOB_TIMEOUT_SECONDS", "360.0"
    )
    worker_job_timeout = float(worker_job_to_raw)

    ret_mode = str(
        overrides.get("retrieval_mode") or os.getenv("RETRIEVAL_MODE", "hybrid")
    ).lower()

    worker_stale_raw = overrides.get("worker_stale_job_timeout_seconds") or os.getenv(
        "WORKER_STALE_JOB_TIMEOUT_SECONDS", "300.0"
    )
    worker_stale_timeout = float(worker_stale_raw)

    max_retries_raw = overrides.get("max_job_retries") or os.getenv(
        "MAX_JOB_RETRIES", "2"
    )
    max_retries = int(max_retries_raw)

    fallback_raw = overrides.get("fallback_to_ollama") or os.getenv(
        "FALLBACK_TO_OLLAMA", "false"
    )
    fallback_val = str(fallback_raw).lower() in ("true", "1", "yes")

    return Settings(
        database_url=db_url,
        embedding_model=emb_model,
        embedding_dimensions=emb_dims,
        chunk_target_tokens=target_tokens,
        chunk_overlap_tokens=overlap_tokens,
        embed_batch_size=batch_size,
        ollama_base_url=ollama_url,
        postgres_db=str(pg_db) if pg_db else None,
        postgres_user=str(pg_user) if pg_user else None,
        chat_provider=chat_prov,
        ollama_chat_model=chat_mod,
        chat_timeout_seconds=chat_timeout,
        retrieval_top_k=ret_top_k,
        retrieval_max_cosine_distance=ret_max_dist,
        chat_max_history_messages=chat_hist,
        litellm_model=str(litellm_mod) if litellm_mod else None,
        litellm_api_key=str(litellm_key) if litellm_key else None,
        litellm_api_base=str(litellm_base) if litellm_base else None,
        litellm_timeout_seconds=litellm_timeout,
        nvidia_base_url=nvidia_base,
        nvidia_model=nvidia_mod,
        nvidia_api_key=str(nvidia_key) if nvidia_key else None,
        nvidia_timeout_seconds=nvidia_timeout,
        chat_orchestrator=chat_orch,
        agent_internal_token=agent_tok,
        pi_agent_host=pi_host,
        pi_agent_port=pi_port,
        pi_agent_request_timeout_seconds=pi_timeout,
        pi_agent_model_provider=pi_provider,
        pi_agent_model_id=pi_model_id,
        pi_agent_model_base_url=pi_base_url,
        pi_agent_model_api_key=pi_api_key,
        writing_target_word_count=writing_words,
        writing_timeout_seconds=writing_timeout,
        redis_url=redis_conn_url,
        worker_concurrency=worker_concurrency,
        worker_job_timeout_seconds=worker_job_timeout,
        retrieval_mode=ret_mode,
        worker_stale_job_timeout_seconds=worker_stale_timeout,
        max_job_retries=max_retries,
        fallback_to_ollama=fallback_val,
    )


_active_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton/current application settings, overridable at runtime."""
    global _active_settings
    if _active_settings is None:
        _active_settings = load_settings()
    return _active_settings


def set_active_settings(settings: Settings) -> None:
    """Set the active application settings instance at runtime."""
    global _active_settings
    _active_settings = settings


def reset_active_settings() -> None:
    """Reset the active settings singleton back to clean defaults."""
    global _active_settings
    _active_settings = None
