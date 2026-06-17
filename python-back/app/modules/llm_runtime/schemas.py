from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.market_data.schemas import QueryMode


LlmRole = Literal["system", "user", "assistant", "tool"]
LlmResponseFormat = Literal["text", "json"]
LlmContextBlockCode = Literal[
    "stock_basic",
    "daily_bars",
    "minute_bars",
    "quote",
    "sectors",
    "fund_flow",
    "lhb",
    "announcements",
    "indicators",
]


class LlmMessage(BaseModel):
    role: LlmRole
    content: str


class LlmProfileConfig(BaseModel):
    config_id: int
    config_code: str
    config_name: str
    provider_code: str
    model_name: str
    api_base_url: str | None = None
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout_seconds: int = 60
    response_format: LlmResponseFormat = "text"
    system_prompt: str | None = None
    max_context_chars: int = 16000
    options: dict = Field(default_factory=dict)


class LlmChatRequest(BaseModel):
    config_id: int | None = None
    config_code: str | None = None
    profile_node_id: int | None = None
    profile_code: str | None = None
    task_id: str | None = None
    messages: list[LlmMessage]
    response_format: LlmResponseFormat | None = None
    metadata: dict = Field(default_factory=dict)


class LlmContextBlock(BaseModel):
    block_code: str
    success: bool
    data: dict | list | str | int | float | bool | None = None
    meta: dict = Field(default_factory=dict)
    error: dict | None = None


class LlmContextPack(BaseModel):
    task_type: str
    stock_code: str | None = None
    query_mode: QueryMode
    allow_provider_refresh: bool = False
    blocks: list[LlmContextBlock] = Field(default_factory=list)
    extra_context: dict = Field(default_factory=dict)
    truncated: bool = False
    created_at: datetime


class LlmAnalysisRequest(BaseModel):
    config_id: int | None = None
    config_code: str | None = None
    profile_node_id: int | None = None
    profile_code: str | None = None
    task_id: str | None = None
    task_type: str = "stock_review"
    stock_code: str | None = None
    user_input: str
    context_blocks: list[LlmContextBlockCode] = Field(
        default_factory=lambda: ["stock_basic", "daily_bars", "quote", "sectors", "fund_flow", "announcements", "indicators"]
    )
    context_limits: dict[str, int] = Field(default_factory=dict)
    query_mode: QueryMode = "db_first"
    allow_provider_refresh: bool = False
    response_format: LlmResponseFormat = "json"
    extra_context: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class LlmChatResult(BaseModel):
    success: bool
    trace_id: str
    config_id: int | None = None
    config_code: str | None = None
    profile_node_id: int | None = None
    provider_code: str | None = None
    model_name: str | None = None
    content: str | None = None
    parsed_json: dict | list | None = None
    usage: dict = Field(default_factory=dict)
    context_pack: LlmContextPack | None = None
    error: dict | None = None


class LlmAnalysisResult(LlmChatResult):
    context_pack: LlmContextPack
