from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.config_center.models import ConfigOption, ConfigValue, RuntimeCallLog, SystemConfig


class LlmRuntimeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_config(self, config_id: int) -> SystemConfig | None:
        result = await self.session.execute(
            select(SystemConfig).where(
                SystemConfig.id == config_id,
                SystemConfig.category_code == "llm",
                SystemConfig.is_enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def find_config(self, config_code: str | None = None) -> SystemConfig | None:
        stmt = select(SystemConfig).where(SystemConfig.category_code == "llm", SystemConfig.is_enabled.is_(True))
        if config_code:
            stmt = stmt.where(SystemConfig.config_code == config_code)
        else:
            stmt = stmt.where(SystemConfig.is_default.is_(True))
        result = await self.session.execute(stmt.order_by(SystemConfig.is_default.desc(), SystemConfig.sort_order, SystemConfig.id).limit(1))
        return result.scalar_one_or_none()

    async def options(self, config_id: int) -> dict:
        result = await self.session.execute(
            select(ConfigOption)
            .where(ConfigOption.system_config_id == config_id, ConfigOption.is_enabled.is_(True))
            .order_by(ConfigOption.option_key)
        )
        return {option.option_key: option.option_value for option in result.scalars().all()}

    async def list_available_values(self, config_id: int, *, value_kind: str = "api_key") -> list[ConfigValue]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(ConfigValue)
            .where(
                ConfigValue.system_config_id == config_id,
                ConfigValue.value_kind == value_kind,
                ConfigValue.is_enabled.is_(True),
                ConfigValue.status == "active",
                or_(ConfigValue.cooldown_until.is_(None), ConfigValue.cooldown_until <= now),
            )
            .order_by(ConfigValue.priority, ConfigValue.weight.desc(), ConfigValue.last_used_at.nullsfirst(), ConfigValue.id)
        )
        return list(result.scalars().all())

    async def mark_value_used(self, value_id: int) -> None:
        await self.session.execute(
            update(ConfigValue)
            .where(ConfigValue.id == value_id)
            .values(last_used_at=datetime.now(timezone.utc), failure_count=0, updated_at=datetime.now(timezone.utc))
        )

    async def mark_value_failure(self, value_id: int) -> None:
        await self.session.execute(
            update(ConfigValue)
            .where(ConfigValue.id == value_id)
            .values(failure_count=ConfigValue.failure_count + 1, updated_at=datetime.now(timezone.utc))
        )

    async def record_call(self, row: dict) -> RuntimeCallLog:
        log = RuntimeCallLog(**row)
        self.session.add(log)
        await self.session.flush()
        return log

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
