from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import SecretCipher
from app.modules.config_center.models import ConfigValue, RuntimeCallLog, SystemConfig
from app.modules.skill_runtime.capabilities import CAPABILITY_CHAINS, CAPABILITY_MIN_RESULTS
from app.modules.skill_runtime.normalizer import result_item_count
from app.modules.skill_runtime.registry import SkillRegistry, SkillSpec
from app.modules.skill_runtime.runner import SkillRunner
from app.modules.skill_runtime.schemas import SkillChainResult, SkillCredential, SkillInfo, SkillRunRequest, SkillRunResult


FAMILY_KEY_MAPPING = {
    "miaoxiang": {"node_code": "miaoxiang_search", "key_env": "EM_API_KEY"},
    "hithink": {"node_code": "iwencai_search", "key_env": "IWENCAI_API_KEY"},
    "kimi": {"node_code": "kimi_search", "key_env": "MOONSHOT_API_KEY"},
}


class SkillRuntimeService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: SkillRegistry | None = None,
        runner: SkillRunner | None = None,
    ) -> None:
        self.session = session
        self.registry = registry or SkillRegistry()
        self.runner = runner or SkillRunner(self.registry)
        self.cipher = SecretCipher(get_settings().config_master_key)

    def list_skills(self) -> list[SkillInfo]:
        return [
            SkillInfo(
                code=skill.code,
                display_name=skill.display_name,
                family=skill.family,
                capabilities=list(skill.capabilities),
                key_env=skill.key_env,
                runtime=skill.runtime,
                args_style=skill.args_style,
                timeout_seconds=skill.timeout_seconds,
                entrypoint=skill.entrypoint,
            )
            for skill in self.registry.list()
        ]

    async def run_skill(
        self,
        skill_code: str,
        payload: SkillRunRequest,
        *,
        trace_id: str | None = None,
        credential: SkillCredential | None = None,
        capability: str | None = None,
    ) -> SkillRunResult:
        trace_id = trace_id or uuid4().hex
        skill = self.registry.get(skill_code)
        if skill is None:
            result = SkillRunResult(success=False, skill_code=skill_code, trace_id=trace_id, query=payload.query, error_code="skill_not_found", error_message=f"skill not found: {skill_code}")
            await self._record_call(result, skill=None, key_id=None, capability=capability)
            await self.session.commit()
            return result
        selected_key_id = credential.key_id if credential else None
        if credential is None:
            credentials = await self._select_credentials(skill)
            if not credentials and skill.key_env:
                result = await self.runner.run(skill.code, payload, trace_id=trace_id, credential=None)
                await self._record_call(result, skill=skill, key_id=None, capability=capability)
                await self.session.commit()
                return result
        else:
            credentials = [credential]

        last_result: SkillRunResult | None = None
        for candidate in credentials or [None]:
            selected_key_id = candidate.key_id if candidate else None
            result = await self.runner.run(skill.code, payload, trace_id=trace_id, credential=candidate)
            last_result = result
            await self._record_call(result, skill=skill, key_id=selected_key_id, capability=capability)
            if result.success:
                if selected_key_id:
                    await self._mark_value_used(selected_key_id)
                await self.session.commit()
                return result
            if selected_key_id:
                await self._mark_value_failure(selected_key_id)
                await self.session.commit()
            if not self._should_try_next_value(result):
                if not selected_key_id:
                    await self.session.commit()
                return result

        await self.session.commit()
        return last_result or SkillRunResult(
            success=False,
            skill_code=skill.code,
            trace_id=trace_id,
            query=payload.query,
            error_code="skill_failed",
            error_message="skill failed without result",
        )

    async def run_capability_chain(self, capability: str, payload: SkillRunRequest, *, trace_id: str | None = None) -> SkillChainResult:
        trace_id = trace_id or uuid4().hex
        chain = CAPABILITY_CHAINS.get(capability) or [skill.code for skill in self.registry.by_capability(capability)]
        results: list[SkillRunResult] = []
        errors: list[dict] = []
        attempted: list[str] = []
        min_results = CAPABILITY_MIN_RESULTS.get(capability, 1)
        for skill_code in chain:
            attempted.append(skill_code)
            result = await self.run_skill(skill_code, payload, trace_id=trace_id, capability=capability)
            results.append(result)
            if result.success and result_item_count(result) >= min_results:
                return SkillChainResult(
                    success=True,
                    capability=capability,
                    trace_id=trace_id,
                    query=payload.query,
                    resolved_skill=skill_code,
                    attempted_skills=attempted,
                    results=results,
                    errors=errors,
                )
            if not result.success:
                errors.append({"skill_code": skill_code, "error_code": result.error_code, "error_message": result.error_message})
        return SkillChainResult(
            success=False,
            capability=capability,
            trace_id=trace_id,
            query=payload.query,
            resolved_skill=None,
            attempted_skills=attempted,
            results=results,
            errors=errors,
        )

    async def _select_credentials(self, skill: SkillSpec) -> list[SkillCredential]:
        if not skill.key_env:
            return []
        mapping = FAMILY_KEY_MAPPING.get(skill.family)
        if mapping is None:
            return []
        keys = await self._select_family_values(str(mapping["node_code"]))
        credentials: list[SkillCredential] = []
        for key in keys:
            try:
                secret_value = self.cipher.decrypt(key.encrypted_value)
            except Exception:
                await self._mark_value_failure(key.id)
                await self.session.commit()
                continue
            credentials.append(
                SkillCredential(
                    key_id=key.id,
                    secret_value=secret_value,
                    key_name=key.value_name,
                    secret_fingerprint=key.fingerprint,
                )
            )
        return credentials

    async def _select_family_values(self, config_code: str) -> list[ConfigValue]:
        config = await self._find_search_config(config_code)
        if config is None:
            return []
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(ConfigValue)
            .where(
                ConfigValue.system_config_id == config.id,
                ConfigValue.value_kind == "api_key",
                ConfigValue.is_enabled.is_(True),
                ConfigValue.status == "active",
                or_(ConfigValue.cooldown_until.is_(None), ConfigValue.cooldown_until <= now),
            )
            .order_by(ConfigValue.priority, ConfigValue.weight.desc(), ConfigValue.last_used_at.nullsfirst(), ConfigValue.id)
        )
        return list(result.scalars().all())

    async def _find_search_config(self, config_code: str) -> SystemConfig | None:
        result = await self.session.execute(
            select(SystemConfig)
            .where(
                SystemConfig.category_code == "search",
                SystemConfig.config_code == config_code,
                SystemConfig.is_enabled.is_(True),
            )
            .order_by(SystemConfig.sort_order, SystemConfig.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _record_call(
        self,
        result: SkillRunResult,
        *,
        skill: SkillSpec | None,
        key_id: int | None,
        capability: str | None,
    ) -> None:
        log = RuntimeCallLog(
            trace_id=result.trace_id,
            domain="skill",
            system_config_id=None,
            config_value_id=key_id,
            capability=capability or (next(iter(skill.capabilities), None) if skill else None),
            call_type="skill_run",
            status="success" if result.success else "failed",
            request_summary={
                "skill_code": result.skill_code,
                "family": skill.family if skill else None,
                "query": result.query[:300],
            },
            response_summary={
                "success": result.success,
                "exit_code": result.exit_code,
                "latency_ms": result.latency_ms,
                "normalized": result.normalized,
                "file_count": len(result.files),
            },
            error_code=result.error_code,
            error_message=(result.error_message or "")[:1000] or None,
            latency_ms=result.latency_ms,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            metadata_json={"runtime": "skill_runtime_v2"},
        )
        self.session.add(log)
        await self.session.flush()

    async def _mark_value_used(self, key_id: int) -> None:
        await self.session.execute(
            update(ConfigValue)
            .where(ConfigValue.id == key_id)
            .values(last_used_at=datetime.now(timezone.utc), failure_count=0, updated_at=datetime.now(timezone.utc))
        )

    async def _mark_value_failure(self, key_id: int) -> None:
        await self.session.execute(
            update(ConfigValue)
            .where(ConfigValue.id == key_id)
            .values(failure_count=ConfigValue.failure_count + 1, updated_at=datetime.now(timezone.utc))
        )

    def _should_try_next_value(self, result: SkillRunResult) -> bool:
        text = f"{result.error_code or ''} {result.error_message or ''} {result.raw_stderr or ''} {result.raw_stdout or ''}".lower()
        return any(marker in text for marker in ("key", "token", "auth", "unauthorized", "forbidden", "401", "403", "invalid", "quota", "rate"))
