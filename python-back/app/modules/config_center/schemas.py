from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ConfigCategory = Literal["search", "llm", "notification"]
ValueStatus = Literal["active", "cooldown", "invalid", "disabled"]


class SystemConfigUpdate(BaseModel):
    config_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    sort_order: int | None = None
    is_default: bool | None = None
    is_enabled: bool | None = None
    metadata: dict | None = None


class SystemConfigRead(BaseModel):
    id: int
    category_code: str
    config_code: str
    config_name: str
    description: str | None = None
    sort_order: int
    is_default: bool
    is_enabled: bool
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ConfigOptionUpsert(BaseModel):
    option_key: str = Field(min_length=1, max_length=120)
    option_name: str = Field(min_length=1, max_length=200)
    value_type: str = "string"
    value: dict | list | str | int | float | bool | None = None
    default_value: dict | list | str | int | float | bool | None = None
    is_required: bool = False
    is_enabled: bool = True
    description: str | None = None
    metadata: dict = Field(default_factory=dict)


class ConfigOptionsPut(BaseModel):
    options: list[ConfigOptionUpsert]


class ConfigOptionRead(BaseModel):
    id: int
    system_config_id: int
    option_key: str
    option_name: str
    value_type: str
    value: dict | list | str | int | float | bool | None = None
    default_value: dict | list | str | int | float | bool | None = None
    is_required: bool
    is_enabled: bool
    description: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ConfigValueCreate(BaseModel):
    value_name: str = Field(min_length=1, max_length=160)
    value_kind: str = "api_key"
    secret: str = Field(min_length=1)
    priority: int = 100
    weight: int = 100
    status: ValueStatus = "active"
    is_enabled: bool = True
    description: str | None = None
    metadata: dict = Field(default_factory=dict)


class ConfigValueUpdate(BaseModel):
    value_name: str | None = Field(default=None, min_length=1, max_length=160)
    value_kind: str | None = None
    secret: str | None = Field(default=None, min_length=1)
    priority: int | None = None
    weight: int | None = None
    status: ValueStatus | None = None
    failure_count: int | None = None
    cooldown_until: datetime | None = None
    is_enabled: bool | None = None
    description: str | None = None
    metadata: dict | None = None


class ConfigValueRead(BaseModel):
    id: int
    system_config_id: int
    value_name: str
    value_kind: str
    fingerprint: str
    priority: int
    weight: int
    status: str
    failure_count: int
    last_used_at: datetime | None = None
    cooldown_until: datetime | None = None
    is_enabled: bool
    description: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ConfigValueTestRead(BaseModel):
    value_id: int
    available: bool
    fingerprint: str
    status: str
    error: str | None = None


class ConfigItemRead(BaseModel):
    config: SystemConfigRead
    options: list[ConfigOptionRead] = Field(default_factory=list)
    values: list[ConfigValueRead] = Field(default_factory=list)
    available_value_count: int = 0


class ConfigSummaryRead(BaseModel):
    categories: dict[str, int] = Field(default_factory=dict)
    active_values: dict[str, int] = Field(default_factory=dict)


class MigrationDryRunRead(BaseModel):
    source_project: str
    legacy_counts: dict[str, int | None] = Field(default_factory=dict)
    planned_steps: list[str]
