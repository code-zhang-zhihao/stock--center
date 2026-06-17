from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def created_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SystemConfig(Base):
    __tablename__ = "t_system_config"
    __table_args__ = (UniqueConstraint("category_code", "config_code", name="uq_t_system_config_category_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_code: Mapped[str] = mapped_column(String(40), nullable=False)
    config_code: Mapped[str] = mapped_column(String(120), nullable=False)
    config_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class ConfigOption(Base):
    __tablename__ = "t_config_option"
    __table_args__ = (UniqueConstraint("system_config_id", "option_key", name="uq_t_config_option_config_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    system_config_id: Mapped[int] = mapped_column(ForeignKey("t_system_config.id", ondelete="CASCADE"), nullable=False)
    option_key: Mapped[str] = mapped_column(String(120), nullable=False)
    option_name: Mapped[str] = mapped_column(String(200), nullable=False)
    value_type: Mapped[str] = mapped_column(String(40), nullable=False, default="string")
    option_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    default_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    is_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class ConfigValue(Base):
    __tablename__ = "t_config_value"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_config_id: Mapped[int] = mapped_column(ForeignKey("t_system_config.id", ondelete="CASCADE"), nullable=False)
    value_name: Mapped[str] = mapped_column(String(160), nullable=False)
    value_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="api_key")
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class RuntimeCallLog(Base):
    __tablename__ = "t_runtime_call_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(80), nullable=False)
    domain: Mapped[str] = mapped_column(String(40), nullable=False)
    system_config_id: Mapped[int | None] = mapped_column(ForeignKey("t_system_config.id", ondelete="SET NULL"))
    config_value_id: Mapped[int | None] = mapped_column(ForeignKey("t_config_value.id", ondelete="SET NULL"))
    capability: Mapped[str | None] = mapped_column(String(120))
    call_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    request_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
