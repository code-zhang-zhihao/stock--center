from datetime import datetime, timezone

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.config_center.models import ConfigOption, ConfigValue, RuntimeCallLog, SystemConfig


class ConfigCenterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_configs(self, *, category_code: str | None = None) -> list[SystemConfig]:
        stmt = select(SystemConfig)
        if category_code:
            stmt = stmt.where(SystemConfig.category_code == category_code)
        result = await self.session.execute(stmt.order_by(SystemConfig.category_code, SystemConfig.sort_order, SystemConfig.id))
        return list(result.scalars().all())

    async def get_config(self, config_id: int) -> SystemConfig | None:
        result = await self.session.execute(select(SystemConfig).where(SystemConfig.id == config_id))
        return result.scalar_one_or_none()

    async def find_config(
        self,
        *,
        category_code: str,
        config_code: str | None = None,
        default: bool = False,
    ) -> SystemConfig | None:
        stmt = select(SystemConfig).where(SystemConfig.category_code == category_code, SystemConfig.is_enabled.is_(True))
        if config_code:
            stmt = stmt.where(SystemConfig.config_code == config_code)
        elif default:
            stmt = stmt.where(SystemConfig.is_default.is_(True))
        result = await self.session.execute(stmt.order_by(SystemConfig.is_default.desc(), SystemConfig.sort_order, SystemConfig.id).limit(1))
        return result.scalar_one_or_none()

    async def update_config(self, config_id: int, values: dict) -> SystemConfig | None:
        if not values:
            return await self.get_config(config_id)
        values["updated_at"] = datetime.now(timezone.utc)
        await self.session.execute(update(SystemConfig).where(SystemConfig.id == config_id).values(**values))
        return await self.get_config(config_id)

    async def clear_default_configs(self, *, category_code: str, exclude_config_id: int) -> None:
        await self.session.execute(
            update(SystemConfig)
            .where(
                SystemConfig.category_code == category_code,
                SystemConfig.id != exclude_config_id,
                SystemConfig.is_default.is_(True),
            )
            .values(is_default=False, updated_at=datetime.now(timezone.utc))
        )

    async def list_options(self, config_id: int, *, only_enabled: bool = False) -> list[ConfigOption]:
        stmt = select(ConfigOption).where(ConfigOption.system_config_id == config_id)
        if only_enabled:
            stmt = stmt.where(ConfigOption.is_enabled.is_(True))
        result = await self.session.execute(stmt.order_by(ConfigOption.option_key, ConfigOption.id))
        return list(result.scalars().all())

    async def upsert_option(self, config_id: int, row: dict) -> ConfigOption:
        row = {**row, "system_config_id": config_id}
        insert_stmt = insert(ConfigOption).values(**row)
        stmt = (
            insert_stmt.on_conflict_do_update(
                index_elements=[ConfigOption.system_config_id, ConfigOption.option_key],
                set_={
                    "option_name": insert_stmt.excluded.option_name,
                    "value_type": insert_stmt.excluded.value_type,
                    "option_value": insert_stmt.excluded.option_value,
                    "default_value": insert_stmt.excluded.default_value,
                    "is_required": insert_stmt.excluded.is_required,
                    "is_enabled": insert_stmt.excluded.is_enabled,
                    "description": insert_stmt.excluded.description,
                    ConfigOption.metadata_json: insert_stmt.excluded.metadata,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            .returning(ConfigOption)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def create_value(self, values: dict) -> ConfigValue:
        result = await self.session.execute(insert(ConfigValue).values(**values).returning(ConfigValue))
        return result.scalar_one()

    async def get_value(self, value_id: int) -> ConfigValue | None:
        result = await self.session.execute(select(ConfigValue).where(ConfigValue.id == value_id))
        return result.scalar_one_or_none()

    async def list_values(
        self,
        config_id: int,
        *,
        value_kind: str | None = None,
        only_available: bool = False,
    ) -> list[ConfigValue]:
        stmt = select(ConfigValue).where(ConfigValue.system_config_id == config_id)
        if value_kind:
            stmt = stmt.where(ConfigValue.value_kind == value_kind)
        if only_available:
            now = datetime.now(timezone.utc)
            stmt = stmt.where(
                ConfigValue.is_enabled.is_(True),
                ConfigValue.status == "active",
                (ConfigValue.cooldown_until.is_(None)) | (ConfigValue.cooldown_until <= now),
            )
        result = await self.session.execute(
            stmt.order_by(ConfigValue.priority, ConfigValue.weight.desc(), ConfigValue.last_used_at.nullsfirst(), ConfigValue.id)
        )
        return list(result.scalars().all())

    async def update_value(self, value_id: int, values: dict) -> ConfigValue | None:
        if not values:
            return await self.get_value(value_id)
        values["updated_at"] = datetime.now(timezone.utc)
        await self.session.execute(update(ConfigValue).where(ConfigValue.id == value_id).values(**values))
        return await self.get_value(value_id)

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

    async def delete_value(self, value_id: int) -> bool:
        result = await self.session.execute(delete(ConfigValue).where(ConfigValue.id == value_id))
        return bool(result.rowcount)

    async def record_call(self, row: dict) -> RuntimeCallLog:
        result = await self.session.execute(insert(RuntimeCallLog).values(**row).returning(RuntimeCallLog))
        return result.scalar_one()

    async def table_count_if_exists(self, table_name: str) -> int | None:
        exists_result = await self.session.execute(select(text("to_regclass(:table_name)")).params(table_name=f"public.{table_name}"))
        if exists_result.scalar_one_or_none() is None:
            return None
        count_result = await self.session.execute(text(f'SELECT count(*) FROM "{table_name}"'))
        return int(count_result.scalar_one())

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
