"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, AsyncIterator
from pydantic import BaseModel


class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMMessage(BaseModel):
    """A message in the conversation."""
    role: LLMRole
    content: str


class LLMResponse(BaseModel):
    """Response from LLM."""
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    raw_response: Optional[dict] = None


class LLMConfig(BaseModel):
    """Configuration for LLM calls."""
    model: str
    temperature: float = 0.7
    max_tokens: int = 2000
    top_p: float = 1.0
    stop_sequences: list[str] = []
    response_format: Optional[str] = None  # "json" for JSON mode


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, api_key: str, config: Optional[LLMConfig] = None):
        self.api_key = api_key
        self.config = config or LLMConfig(model=self.default_model)

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider."""
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model for this provider."""
        pass

    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream a response from the LLM."""
        pass

    async def generate_simple(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        config: Optional[LLMConfig] = None,
    ) -> str:
        """Simple interface for single prompt generation."""
        messages = []

        if system_prompt:
            messages.append(LLMMessage(role=LLMRole.SYSTEM, content=system_prompt))

        messages.append(LLMMessage(role=LLMRole.USER, content=prompt))

        response = await self.generate(messages, config)
        return response.content

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        config: Optional[LLMConfig] = None,
    ) -> dict:
        """Generate a JSON response."""
        import json

        config = config or self.config.model_copy()
        config.response_format = "json"

        if system_prompt:
            system_prompt += "\n\nRespond with valid JSON only."
        else:
            system_prompt = "Respond with valid JSON only."

        content = await self.generate_simple(prompt, system_prompt, config)

        # Try to extract JSON from response
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        return json.loads(content.strip())

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text. Override in subclasses that support it."""
        raise NotImplementedError(f"{self.provider_name} does not support embeddings")
