from typing import Any

import httpx

from app.modules.llm_runtime.schemas import LlmMessage, LlmProfileConfig, LlmResponseFormat


class OpenAICompatibleProvider:
    async def chat(
        self,
        *,
        profile: LlmProfileConfig,
        api_key: str,
        messages: list[LlmMessage],
        response_format: LlmResponseFormat,
    ) -> dict[str, Any]:
        if not profile.api_base_url:
            raise ValueError(f"LLM config has no api_base_url: {profile.config_code}")
        body: dict[str, Any] = {
            "model": profile.model_name,
            "messages": [message.model_dump() for message in messages],
            "temperature": profile.temperature,
            "max_tokens": profile.max_tokens,
        }
        if response_format == "json":
            body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=profile.timeout_seconds) as client:
            response = await client.post(
                f"{profile.api_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            return response.json()


def extract_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return content or ""
