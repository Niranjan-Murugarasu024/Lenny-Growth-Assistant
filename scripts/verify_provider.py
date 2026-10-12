"""Manual Chat Provider Verification Script.

Dispatches a single, explicit test prompt through the configured inference provider
(local Ollama or cloud LiteLLM) to verify connectivity, configuration, and generation.

Usage:
    python scripts/verify_provider.py

Exit codes:
    0: Success
    1: Provider error or failure

NOTE: If CHAT_PROVIDER is configured to a cloud provider (e.g. LiteLLM with OpenAI,
Anthropic, NVIDIA NIM), this script will make an actual API call that may consume
quota or incur usage costs under your account.
"""

from __future__ import annotations

from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings
from backend.app.rag.factory import get_chat_provider
from backend.app.rag.provider_base import ProviderError


def verify_configured_provider() -> int:
    settings = get_settings()

    print("=" * 75)
    print("THE LENNY GROWTH ASSISTANT - MANUAL CHAT PROVIDER VERIFICATION")
    print("=" * 75)

    print(f"Configured Provider : {settings.chat_provider}")
    if settings.chat_provider.lower().strip() == "ollama":
        print(f"Ollama Server Base  : {settings.ollama_base_url}")
        print(f"Ollama Chat Model   : {settings.ollama_chat_model}")
        print(f"Timeout (seconds)   : {settings.chat_timeout_seconds}")
    else:
        print(f"LiteLLM Model       : {settings.litellm_model or '(not set)'}")
        print(f"LiteLLM API Key     : {settings.sanitized_litellm_api_key() or '(not set)'}")
        print(f"LiteLLM API Base    : {settings.litellm_api_base or '(default)'}")
        print(f"Timeout (seconds)   : {settings.litellm_timeout_seconds}")

    print("\n[Step 1] Instantiating provider via central factory...")
    try:
        provider = get_chat_provider(settings)
        print(f"Provider Instantiated: name={provider.name!r}, model={provider.model_name!r}")
    except Exception as exc:
        print(f"\n[FAIL] Failed to instantiate provider: {exc}")
        return 1

    print("\n[Step 2] Executing provider readiness / health check...")
    try:
        health = provider.check_health()
        print(f"Health Check Result: {health}")
        if not health.get("available"):
            print(f"\n[FAIL] Provider reports unhealthy / unavailable: {health.get('error', 'unknown error')}")
            return 1
    except Exception as exc:
        print(f"\n[FAIL] Unexpected error during health check: {exc}")
        return 1

    print("\n[Step 3] Dispatching explicit test completion prompt...")
    test_messages = [
        {"role": "system", "content": "You are a helpful assistant for product leaders."},
        {"role": "user", "content": "Reply in one concise sentence: What is the main objective of product management?"},
    ]

    t0 = time.time()
    try:
        response = provider.generate_chat_response(messages=test_messages, temperature=0.2)
        elapsed = time.time() - t0
    except ProviderError as exc:
        elapsed = time.time() - t0
        print(f"\n[FAIL] Provider generation failed after {elapsed:.2f}s: {exc}")
        return 1
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"\n[FAIL] Unexpected error after {elapsed:.2f}s: {exc}")
        return 1

    content = response.get("content", "").strip()
    returned_model = response.get("model", provider.model_name)
    usage = response.get("usage", {})

    print(f"\n[SUCCESS] Completed in {elapsed:.2f}s")
    print(f"Returned Model     : {returned_model}")
    if usage:
        print(f"Token Usage        : {usage}")
    print("\nAnswer Excerpt:")
    print("-" * 50)
    print(content)
    print("-" * 50)

    print("\n" + "=" * 75)
    print("RESULT: CHAT PROVIDER VERIFICATION SUCCEEDED!")
    print("=" * 75)
    return 0


if __name__ == "__main__":
    sys.exit(verify_configured_provider())
