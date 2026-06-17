import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import SecretCipher
from app.modules.config_center.models import ConfigValue, SystemConfig
from app.modules.llm_runtime.context import LlmContextProvider, MarketDataContextProvider
from app.modules.llm_runtime.providers import OpenAICompatibleProvider, extract_content
from app.modules.llm_runtime.repository import LlmRuntimeRepository
from app.modules.llm_runtime.schemas import (
    LlmAnalysisRequest,
    LlmAnalysisResult,
    LlmChatRequest,
    LlmChatResult,
    LlmContextPack,
    LlmMessage,
    LlmProfileConfig,
    LlmResponseFormat,
)


DEFAULT_BASE_URLS = {
    "kimi_llm": "https://api.moonshot.cn/v1",
    "deepseek_llm": "https://api.deepseek.com",
    "aliyun_coding_plan": "https://coding.dashscope.aliyuncs.com/v1",
    "volcengine_coding_plan": "https://ark.cn-beijing.volces.com/api/coding/v3",
    "openai_compatible": None,
}


class LlmRuntimeService:
    def __init__(
        self,
        repository: LlmRuntimeRepository,
        session: AsyncSession,
        *,
        provider: OpenAICompatibleProvider | None = None,
        context_provider: LlmContextProvider | None = None,
    ) -> None:
        self.repository = repository
        self.provider = provider or OpenAICompatibleProvider()
        self.context_provider = context_provider or MarketDataContextProvider(session)
        self.cipher = SecretCipher(get_settings().config_master_key)

    async def chat(self, payload: LlmChatRequest) -> LlmChatResult:
        trace_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        started_perf = perf_counter()
        try:
            profile = await self._load_profile(payload.config_id or payload.profile_node_id, payload.config_code or payload.profile_code)
            response_format = payload.response_format or profile.response_format
            return await self._chat_with_profile(
                trace_id=trace_id,
                started_at=started_at,
                started_perf=started_perf,
                profile=profile,
                messages=payload.messages,
                response_format=response_format,
                call_type="chat",
                request_summary={
                    "task_id": payload.task_id,
                    "message_count": len(payload.messages),
                    "message_chars": sum(len(message.content) for message in payload.messages),
                    "response_format": response_format,
                    "metadata": self._safe_summary(payload.metadata),
                },
            )
        except Exception as exc:
            return await self._record_failure(
                trace_id=trace_id,
                started_at=started_at,
                started_perf=started_perf,
                call_type="chat",
                code="llm_chat_failed",
                message=str(exc),
            )

    async def analyze_with_context(self, payload: LlmAnalysisRequest) -> LlmAnalysisResult:
        trace_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        started_perf = perf_counter()
        context_pack: LlmContextPack | None = None
        try:
            profile = await self._load_profile(payload.config_id or payload.profile_node_id, payload.config_code or payload.profile_code)
            context_pack = await self.context_provider.build(payload)
            context_json = self._context_json(context_pack, profile.max_context_chars)
            if len(context_json) >= profile.max_context_chars:
                context_pack.truncated = True
            messages = [
                LlmMessage(role="system", content=self._system_prompt(profile)),
                LlmMessage(
                    role="user",
                    content=(
                        "请基于以下固定上下文包完成分析。只能使用上下文中的事实；"
                        "如果数据缺失，请明确说明缺失项，不要编造。\n\n"
                        f"用户问题：{payload.user_input}\n\n"
                        f"上下文 JSON：\n{context_json}"
                    ),
                ),
            ]
            result = await self._chat_with_profile(
                trace_id=trace_id,
                started_at=started_at,
                started_perf=started_perf,
                profile=profile,
                messages=messages,
                response_format=payload.response_format,
                call_type="analysis",
                context_pack=context_pack,
                request_summary={
                    "task_id": payload.task_id,
                    "task_type": payload.task_type,
                    "stock_code": payload.stock_code,
                    "context_blocks": payload.context_blocks,
                    "context_block_count": len(context_pack.blocks),
                    "context_chars": len(context_json),
                    "context_truncated": context_pack.truncated,
                    "query_mode": context_pack.query_mode,
                    "allow_provider_refresh": context_pack.allow_provider_refresh,
                    "response_format": payload.response_format,
                    "metadata": self._safe_summary(payload.metadata),
                },
            )
            result_payload = result.model_dump()
            result_payload["context_pack"] = context_pack
            return LlmAnalysisResult(**result_payload)
        except Exception as exc:
            failed = await self._record_failure(
                trace_id=trace_id,
                started_at=started_at,
                started_perf=started_perf,
                call_type="analysis",
                code="llm_analysis_failed",
                message=str(exc),
                context_pack=context_pack,
            )
            fallback_pack = context_pack or LlmContextPack(
                task_type=payload.task_type,
                stock_code=payload.stock_code,
                query_mode=payload.query_mode,
                allow_provider_refresh=payload.allow_provider_refresh,
                blocks=[],
                extra_context=payload.extra_context,
                created_at=datetime.now(timezone.utc),
            )
            failed_payload = failed.model_dump()
            failed_payload["context_pack"] = fallback_pack
            return LlmAnalysisResult(**failed_payload)

    async def analyze_json(self, payload: LlmAnalysisRequest) -> LlmAnalysisResult:
        return await self.analyze_with_context(payload.model_copy(update={"response_format": "json"}))

    async def _chat_with_profile(
        self,
        *,
        trace_id: str,
        started_at: datetime,
        started_perf: float,
        profile: LlmProfileConfig,
        messages: list[LlmMessage],
        response_format: LlmResponseFormat,
        call_type: str,
        request_summary: dict,
        context_pack: LlmContextPack | None = None,
    ) -> LlmChatResult:
        keys = await self._select_keys(profile.config_id)
        if not keys:
            return await self._record_failure(
                trace_id=trace_id,
                started_at=started_at,
                started_perf=started_perf,
                call_type=call_type,
                code="llm_key_missing",
                message=f"LLM config has no active key: {profile.config_code}",
                profile=profile,
                context_pack=context_pack,
                request_summary=request_summary,
            )
        last_error: Exception | None = None
        last_key: ConfigValue | None = None
        for key in keys:
            last_key = key
            try:
                api_key = self.cipher.decrypt(key.encrypted_value)
                payload = await self.provider.chat(
                    profile=profile,
                    api_key=api_key,
                    messages=messages,
                    response_format=response_format,
                )
                content = extract_content(payload)
                usage = payload.get("usage") or {}
                parsed_json = self._parse_json(content) if response_format == "json" else None
                await self.repository.mark_value_used(key.id)
                await self.repository.record_call(
                    self._log_row(
                        trace_id=trace_id,
                        profile=profile,
                        key=key,
                        call_type=call_type,
                        status="success",
                        request_summary=request_summary,
                        response_summary={
                            "usage": usage,
                            "content_preview": (content or "")[:500],
                            "parsed_json_ok": parsed_json is not None if response_format == "json" else None,
                        },
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                )
                await self.repository.commit()
                return LlmChatResult(
                    success=True,
                    trace_id=trace_id,
                    config_id=profile.config_id,
                    config_code=profile.config_code,
                    profile_node_id=profile.config_id,
                    provider_code=profile.provider_code,
                    model_name=profile.model_name,
                    content=content,
                    parsed_json=parsed_json,
                    usage=usage,
                    context_pack=context_pack,
                    error=None,
                )
            except Exception as exc:
                last_error = exc
                await self.repository.mark_value_failure(key.id)
                await self.repository.commit()
                if not self._should_try_next_key(exc):
                    break
        return await self._record_failure(
            trace_id=trace_id,
            started_at=started_at,
            started_perf=started_perf,
            call_type=call_type,
            code="llm_provider_call_failed",
            message=str(last_error) if last_error else "LLM provider call failed",
            profile=profile,
            key=last_key,
            context_pack=context_pack,
            request_summary=request_summary,
        )

    async def _load_profile(self, config_id: int | None, config_code: str | None) -> LlmProfileConfig:
        config = await self.repository.get_config(config_id) if config_id else await self.repository.find_config(config_code)
        if config is None:
            raise ValueError(f"LLM config not found: {config_id or config_code or '<default>'}")
        options = await self.repository.options(config.id)
        provider_code = str(options.get("provider_code") or config.config_code)
        model_name = str(options.get("model_name") or self._default_model_name(provider_code, config.config_code))
        api_base_url = self._optional_string(options.get("api_base_url")) or DEFAULT_BASE_URLS.get(provider_code)
        return LlmProfileConfig(
            config_id=config.id,
            config_code=config.config_code,
            config_name=config.config_name,
            provider_code=provider_code,
            model_name=model_name,
            api_base_url=api_base_url,
            temperature=float(options.get("temperature") or 0.2),
            max_tokens=int(options.get("max_tokens") or 2048),
            timeout_seconds=int(options.get("timeout_seconds") or 60),
            response_format=self._response_format(options.get("response_format")),
            system_prompt=self._optional_string(options.get("system_prompt")),
            max_context_chars=int(options.get("max_context_chars") or 16000),
            options=options,
        )

    async def _select_keys(self, config_id: int) -> list[ConfigValue]:
        return await self.repository.list_available_values(config_id, value_kind="api_key")

    async def _record_failure(
        self,
        *,
        trace_id: str,
        started_at: datetime,
        started_perf: float,
        call_type: str,
        code: str,
        message: str,
        profile: LlmProfileConfig | None = None,
        key: ConfigValue | None = None,
        context_pack: LlmContextPack | None = None,
        request_summary: dict | None = None,
    ) -> LlmChatResult:
        await self.repository.record_call(
            self._log_row(
                trace_id=trace_id,
                profile=profile,
                key=key,
                call_type=call_type,
                status="failed",
                request_summary=request_summary or {},
                response_summary={},
                error_code=code,
                error_message=message,
                started_at=started_at,
                started_perf=started_perf,
            )
        )
        await self.repository.commit()
        return LlmChatResult(
            success=False,
            trace_id=trace_id,
            profile_node_id=profile.config_id if profile else None,
            config_id=profile.config_id if profile else None,
            config_code=profile.config_code if profile else None,
            provider_code=profile.provider_code if profile else None,
            model_name=profile.model_name if profile else None,
            content=None,
            parsed_json=None,
            usage={},
            context_pack=context_pack,
            error={"code": code, "message": message},
        )

    def _log_row(
        self,
        *,
        trace_id: str,
        profile: LlmProfileConfig | None,
        key: ConfigValue | None,
        call_type: str,
        status: str,
        request_summary: dict,
        response_summary: dict,
        started_at: datetime,
        started_perf: float,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        return {
            "trace_id": trace_id,
            "domain": "llm",
            "system_config_id": profile.config_id if profile else None,
            "config_value_id": key.id if key else None,
            "capability": "llm_chat" if call_type == "chat" else "llm_analysis",
            "call_type": call_type,
            "status": status,
            "request_summary": self._safe_summary(request_summary),
            "response_summary": self._safe_summary(response_summary),
            "error_code": error_code,
            "error_message": self._safe_error_message(error_message),
            "latency_ms": int((perf_counter() - started_perf) * 1000),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
            "metadata_json": {"runtime": "llm_runtime_v2"},
        }

    def _context_json(self, context_pack: LlmContextPack, max_chars: int) -> str:
        payload = context_pack.model_dump(mode="json")
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 80)] + "\n...<context_truncated>"

    def _system_prompt(self, profile: LlmProfileConfig) -> str:
        return profile.system_prompt or "你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"

    def _parse_json(self, content: str | None):
        if not content:
            return None
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
            return None

    def _response_format(self, value: Any) -> LlmResponseFormat:
        return "json" if value == "json" else "text"

    def _optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _default_model_name(self, provider_code: str, profile_code: str) -> str:
        defaults = {
            ("kimi_llm", "kimi_llm"): "moonshot-v1-8k",
            ("moonshot_v1_8k", "moonshot_v1_8k"): "moonshot-v1-8k",
            ("moonshot_v1_32k", "moonshot_v1_32k"): "moonshot-v1-32k",
            ("deepseek_llm", "deepseek_chat"): "deepseek-chat",
            ("aliyun_coding_plan", "aliyun_coding_plan"): "qwen3-coder-next",
            ("volcengine_coding_plan", "volcengine_coding_plan"): "ark-code-latest",
            ("openai_compatible", "default"): "gpt-4o-mini",
        }
        return defaults.get((provider_code, profile_code), profile_code.replace("_", "-"))

    def _should_try_next_key(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return any(marker in text for marker in ("401", "403", "unauthorized", "forbidden", "invalid", "quota", "rate"))

    def _safe_summary(self, payload: dict | None) -> dict:
        if not payload:
            return {}
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) <= 4000:
            return payload
        return {"truncated": True, "char_count": len(text), "preview": text[:2000]}

    def _safe_error_message(self, message: str | None) -> str | None:
        if message is None:
            return None
        return message[:1000]
