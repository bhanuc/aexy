"""LLM provider factory."""

from typing import Optional

from mailagent.llm.base import LLMProvider, LLMConfig
from mailagent.llm.claude import ClaudeProvider
from mailagent.llm.gemini import GeminiProvider
from mailagent.config import get_settings


def get_llm_provider(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    config: Optional[LLMConfig] = None,
) -> LLMProvider:
    """Get an LLM provider instance.

    Args:
        provider: Provider name ("claude", "gemini", "openai")
        api_key: API key (uses env var if not provided)
        config: LLM configuration

    Returns:
        LLMProvider instance
    """
    settings = get_settings()

    # Default to settings if not specified
    provider = provider or getattr(settings, "default_llm_provider", "gemini")

    providers = {
        "claude": (ClaudeProvider, "ANTHROPIC_API_KEY"),
        "anthropic": (ClaudeProvider, "ANTHROPIC_API_KEY"),
        "gemini": (GeminiProvider, "GEMINI_API_KEY"),
        "google": (GeminiProvider, "GEMINI_API_KEY"),
    }

    if provider.lower() not in providers:
        raise ValueError(f"Unknown LLM provider: {provider}. Available: {list(providers.keys())}")

    provider_class, env_key = providers[provider.lower()]

    # Get API key from settings or environment
    if not api_key:
        import os
        api_key = getattr(settings, env_key.lower(), None) or os.getenv(env_key)

    if not api_key:
        raise ValueError(f"No API key found for {provider}. Set {env_key} environment variable.")

    return provider_class(api_key=api_key, config=config)
