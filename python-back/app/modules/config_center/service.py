from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import get_settings
from app.core.security import SecretCipher, build_secret_fingerprint
from app.modules.config_center.models import ConfigOption, ConfigValue, SystemConfig
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.config_center.schemas import (
    ConfigItemRead,
    ConfigOptionRead,
    ConfigOptionUpsert,
    ConfigSummaryRead,
    ConfigValueCreate,
    ConfigValueRead,
    ConfigValueTestRead,
    ConfigValueUpdate,
    MigrationDryRunRead,
    SystemConfigRead,
    SystemConfigUpdate,
)


class ConfigCenterService:
    def __init__(self, repository: ConfigCenterRepository) -> None:
        self.repository = repository
        self.cipher = SecretCipher(get_settings().config_master_key)

    async def list_items(self, *, category_code: str) -> list[ConfigItemRead]:
        configs = await self.repository.list_configs(category_code=category_code)
        items = []
        for config in configs:
            options = await self.repository.list_options(config.id)
            values = await self.repository.list_values(config.id)
            items.append(
                ConfigItemRead(
                    config=self._config_read(config),
                    options=[self._option_read(option) for option in options],
                    values=[self._value_read(value) for value in values],
                    available_value_count=len([value for value in values if value.status == "active" and value.is_enabled]),
                )
            )
        return items

    async def summary(self) -> ConfigSummaryRead:
        categories = ["search", "llm", "notification", "market_data"]
        configs_by_category = {category: await self.repository.list_configs(category_code=category) for category in categories}
        active_values = {}
        for category, configs in configs_by_category.items():
            count = 0
            for config in configs:
                count += len(await self.repository.list_values(config.id, only_available=True))
            active_values[category] = count
        return ConfigSummaryRead(
            categories={category: len(configs) for category, configs in configs_by_category.items()},
            active_values=active_values,
        )

    async def get_config(self, category_code: str, config_code: str | None = None, *, default: bool = False) -> SystemConfig | None:
        return await self.repository.find_config(category_code=category_code, config_code=config_code, default=default)

    async def update_item(self, config_id: int, payload: SystemConfigUpdate) -> SystemConfigRead | None:
        values = payload.model_dump(exclude_unset=True)
        if "metadata" in values:
            values["metadata_json"] = values.pop("metadata")
        config = await self.repository.update_config(config_id, values)
        if config and values.get("is_default") is True:
            await self.repository.clear_default_configs(category_code=config.category_code, exclude_config_id=config.id)
        await self.repository.commit()
        return self._config_read(config) if config else None

    async def list_options(self, config_id: int) -> list[ConfigOptionRead]:
        await self._require_config(config_id)
        options = await self.repository.list_options(config_id)
        return [self._option_read(option) for option in options]

    async def put_options(self, config_id: int, payloads: list[ConfigOptionUpsert]) -> list[ConfigOptionRead]:
        await self._require_config(config_id)
        rows = []
        for payload in payloads:
            row = payload.model_dump()
            row["option_value"] = row.pop("value")
            row["metadata_json"] = row.pop("metadata")
            rows.append(await self.repository.upsert_option(config_id, row))
        await self.repository.commit()
        return [self._option_read(row) for row in rows]

    async def list_values(
        self,
        config_id: int,
        *,
        value_kind: str | None = None,
        only_available: bool = False,
    ) -> list[ConfigValueRead]:
        await self._require_config(config_id)
        values = await self.repository.list_values(config_id, value_kind=value_kind, only_available=only_available)
        return [self._value_read(value) for value in values]

    async def create_value(self, config_id: int, payload: ConfigValueCreate) -> ConfigValueRead:
        config = await self._require_config(config_id)
        self._validate_endpoint_url(config, payload.value_kind, payload.endpoint_url)
        secret = payload.secret
        values = payload.model_dump(exclude={"secret"})
        values["system_config_id"] = config_id
        values["encrypted_value"] = self.cipher.encrypt(secret)
        values["fingerprint"] = build_secret_fingerprint(secret)
        values["metadata_json"] = values.pop("metadata")
        value = await self.repository.create_value(values)
        await self.repository.commit()
        return self._value_read(value)

    async def update_value(self, value_id: int, payload: ConfigValueUpdate) -> ConfigValueRead | None:
        existing = await self.repository.get_value(value_id)
        if existing is None:
            return None
        config = await self._require_config(existing.system_config_id)
        values = payload.model_dump(exclude_unset=True)
        self._validate_endpoint_url(
            config,
            values.get("value_kind", existing.value_kind),
            values.get("endpoint_url", existing.endpoint_url),
        )
        secret = values.pop("secret", None)
        if secret is not None:
            values["encrypted_value"] = self.cipher.encrypt(secret)
            values["fingerprint"] = build_secret_fingerprint(secret)
        if "metadata" in values:
            values["metadata_json"] = values.pop("metadata")
        value = await self.repository.update_value(value_id, values)
        await self.repository.commit()
        return self._value_read(value) if value else None

    async def disable_value(self, value_id: int) -> ConfigValueRead | None:
        value = await self.repository.update_value(value_id, {"status": "disabled", "is_enabled": False})
        await self.repository.commit()
        return self._value_read(value) if value else None

    async def delete_value(self, value_id: int) -> bool:
        deleted = await self.repository.delete_value(value_id)
        await self.repository.commit()
        return deleted

    async def test_value(self, value_id: int) -> ConfigValueTestRead | None:
        value = await self.repository.get_value(value_id)
        if value is None:
            return None
        error = None
        available = False
        details: dict = {}
        try:
            secret = self.cipher.decrypt(value.encrypted_value)
            available = bool(secret) and build_secret_fingerprint(secret) == value.fingerprint
            config = await self.repository.get_config(value.system_config_id)
            if available and config and config.category_code == "market_data" and config.config_code == "tushare_pro":
                from app.modules.market_data.tushare_runtime import TushareProviderFactory

                probe = await TushareProviderFactory(self.repository).probe_value(value_id)
                available = probe.available
                error = probe.error
                details = probe.details
            elif available and config and config.category_code == "market_data" and config.config_code == "redis_cache":
                from app.core.redis_client import redis_client

                probe = await redis_client.test_url(secret)
                available = bool(probe.get("available"))
                error = probe.get("error")
                details = {key: value for key, value in probe.items() if key not in {"available", "error"}}
            elif available and config and config.category_code == "market_data" and config.config_code == "tickflow":
                from app.modules.realtime_market.tickflow_runtime import TickflowProviderFactory

                probe = await TickflowProviderFactory(self.repository).probe_value(value_id)
                available = probe.available
                error = probe.error
                details = probe.details
        except Exception as exc:
            error = str(exc)
        await self.repository.record_call(
            {
                "trace_id": uuid4().hex,
                "domain": "config",
                "system_config_id": value.system_config_id,
                "config_value_id": value.id,
                "capability": "test_value",
                "call_type": "test_value",
                "status": "success" if available else "failed",
                "request_summary": {"value_id": value.id},
                "response_summary": {"available": available, "fingerprint": value.fingerprint, "details": details},
                "error_code": None if available else "config_value_test_failed",
                "error_message": error,
                "finished_at": datetime.now(timezone.utc),
                "metadata_json": {"runtime": "config_center_v2"},
            }
        )
        await self.repository.commit()
        return ConfigValueTestRead(
            value_id=value.id,
            available=available,
            fingerprint=value.fingerprint,
            status=value.status,
            error=error,
            details=details,
        )

    async def migration_dry_run(self) -> MigrationDryRunRead:
        table_names = [
            "provider",
            "provider_key",
            "provider_capability_route",
            "llm_model_profile",
            "t_config_node",
            "t_secret_key",
            "t_config_relation",
            "t_system_config",
            "t_config_value",
            "t_config_option",
        ]
        legacy_counts = {
            table_name: await self.repository.table_count_if_exists(table_name)
            for table_name in table_names
        }
        return MigrationDryRunRead(
            source_project="/Volumes/TiPro9000/projects/archived/stock-analysis",
            legacy_counts=legacy_counts,
            planned_steps=[
                "t_config_node/t_secret_key/t_config_option -> t_system_config/t_config_value/t_config_option",
                "provider_key -> t_config_value when legacy provider_key still exists",
                "drop t_config_node, t_secret_key, t_config_relation after validation",
                "runtime reads only t_system_config, t_config_value, t_config_option",
            ],
        )

    async def _require_config(self, config_id: int) -> SystemConfig:
        config = await self.repository.get_config(config_id)
        if config is None:
            raise ValueError(f"config item not found: {config_id}")
        return config

    def _config_read(self, config: SystemConfig) -> SystemConfigRead:
        return SystemConfigRead(
            id=config.id,
            category_code=config.category_code,
            config_code=config.config_code,
            config_name=config.config_name,
            description=config.description,
            sort_order=config.sort_order,
            is_default=config.is_default,
            is_enabled=config.is_enabled,
            metadata=config.metadata_json,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    def _option_read(self, option: ConfigOption) -> ConfigOptionRead:
        return ConfigOptionRead(
            id=option.id,
            system_config_id=option.system_config_id,
            option_key=option.option_key,
            option_name=option.option_name,
            value_type=option.value_type,
            value=option.option_value,
            default_value=option.default_value,
            is_required=option.is_required,
            is_enabled=option.is_enabled,
            description=option.description,
            metadata=option.metadata_json,
            created_at=option.created_at,
            updated_at=option.updated_at,
        )

    def _value_read(self, value: ConfigValue) -> ConfigValueRead:
        return ConfigValueRead(
            id=value.id,
            system_config_id=value.system_config_id,
            value_name=value.value_name,
            value_kind=value.value_kind,
            endpoint_url=value.endpoint_url,
            fingerprint=value.fingerprint,
            priority=value.priority,
            weight=value.weight,
            status=value.status,
            failure_count=value.failure_count,
            last_used_at=value.last_used_at,
            cooldown_until=value.cooldown_until,
            is_enabled=value.is_enabled,
            description=value.description,
            metadata=value.metadata_json,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _validate_endpoint_url(config: SystemConfig, value_kind: str, endpoint_url: str | None) -> None:
        if endpoint_url is None:
            return
        supported = (
            (config.category_code == "market_data" and config.config_code == "tushare_pro" and value_kind == "token")
            or (config.category_code == "market_data" and config.config_code == "tickflow" and value_kind == "api_key")
        )
        if not supported:
            raise ValueError("endpoint_url is only supported by market_data/tushare_pro tokens or market_data/tickflow API keys")
