"""Google Gemini LLM provider."""

import httpx
from typing import Optional, AsyncIterator

from mailagent.llm.base import LLMProvider, LLMConfig, LLMMessage, LLMResponse, LLMRole


class GeminiProvider(LLMProvider):
    """Google Gemini provider."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return "gemini-2.0-flash"

    def _convert_messages(self, messages: list[LLMMessage]) -> tuple[str, list[dict]]:
        """Convert messages to Gemini format."""
        system_prompt = ""
        gemini_contents = []

        for msg in messages:
            if msg.role == LLMRole.SYSTEM:
                system_prompt = msg.content
            else:
                role = "user" if msg.role == LLMRole.USER else "model"
                gemini_contents.append({
                    "role": role,
                    "parts": [{"text": msg.content}],
                })

        return system_prompt, gemini_contents

    async def generate(
        self,
        messages: list[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        """Generate response from Gemini."""
        config = config or self.config
        system_prompt, contents = self._convert_messages(messages)

        request_body = {
            "contents": contents,
            "generationConfig": {
                "temperature": config.temperature,
                "maxOutputTokens": config.max_tokens,
                "topP": config.top_p,
            },
        }

        if system_prompt:
            request_body["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/models/{config.model}:generateContent",
                params={"key": self.api_key},
                json=request_body,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

        candidate = data["candidates"][0]
        content = candidate["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})

        return LLMResponse(
            content=content,
            model=config.model,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            finish_reason=candidate.get("finishReason", "STOP"),
            raw_response=data,
        )

    async def generate_stream(
        self,
        messages: list[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream response from Gemini."""
        config = config or self.config
        system_prompt, contents = self._convert_messages(messages)

        request_body = {
            "contents": contents,
            "generationConfig": {
                "temperature": config.temperature,
                "maxOutputTokens": config.max_tokens,
            },
        }

        if system_prompt:
            request_body["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.BASE_URL}/models/{config.model}:streamGenerateContent",
                params={"key": self.api_key, "alt": "sse"},
                json=request_body,
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        data = json.loads(line[6:])
                        if "candidates" in data:
                            parts = data["candidates"][0]["content"]["parts"]
                            if parts:
                                yield parts[0].get("text", "")

    async def embed(self, text: str) -> list[float]:
        """Generate embedding using Gemini."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/models/text-embedding-004:embedContent",
                params={"key": self.api_key},
                json={
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": text}]},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

        return data["embedding"]["values"]
