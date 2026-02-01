"""Claude (Anthropic) LLM provider."""

import httpx
from typing import Optional, AsyncIterator

from mailagent.llm.base import LLMProvider, LLMConfig, LLMMessage, LLMResponse, LLMRole


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider."""

    BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def default_model(self) -> str:
        return "claude-3-opus-20240229"

    def _convert_messages(self, messages: list[LLMMessage]) -> tuple[str, list[dict]]:
        """Convert messages to Claude format."""
        system_prompt = ""
        claude_messages = []

        for msg in messages:
            if msg.role == LLMRole.SYSTEM:
                system_prompt = msg.content
            else:
                claude_messages.append({
                    "role": msg.role.value,
                    "content": msg.content,
                })

        return system_prompt, claude_messages

    async def generate(
        self,
        messages: list[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        """Generate response from Claude."""
        config = config or self.config
        system_prompt, claude_messages = self._convert_messages(messages)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.API_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": config.model,
                    "max_tokens": config.max_tokens,
                    "temperature": config.temperature,
                    "system": system_prompt,
                    "messages": claude_messages,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

        return LLMResponse(
            content=data["content"][0]["text"],
            model=data["model"],
            input_tokens=data["usage"]["input_tokens"],
            output_tokens=data["usage"]["output_tokens"],
            finish_reason=data["stop_reason"],
            raw_response=data,
        )

    async def generate_stream(
        self,
        messages: list[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream response from Claude."""
        config = config or self.config
        system_prompt, claude_messages = self._convert_messages(messages)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.BASE_URL}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.API_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": config.model,
                    "max_tokens": config.max_tokens,
                    "temperature": config.temperature,
                    "system": system_prompt,
                    "messages": claude_messages,
                    "stream": True,
                },
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        data = json.loads(line[6:])
                        if data["type"] == "content_block_delta":
                            yield data["delta"]["text"]
