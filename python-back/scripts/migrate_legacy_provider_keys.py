"""Migrate legacy provider_key rows into t_config_value.

The legacy stock-analysis project stores secrets in provider_key.encrypted_key
using the same Fernet-based CONFIG_MASTER_KEY cipher as stock-center. This
script preserves ciphertext and fingerprints without printing secret values.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.security import SecretCipher, build_secret_fingerprint
from app.db.session import get_sessionmaker


FAMILY_PROVIDER_MAPPING = {
    "mx_finance_search": ("search", "miaoxiang_search", "EM_API_KEY"),
    "mx_finance_data": ("search", "miaoxiang_search", "EM_API_KEY"),
    "mx_macro_data": ("search", "miaoxiang_search", "EM_API_KEY"),
    "mx_stocks_screener": ("search", "miaoxiang_search", "EM_API_KEY"),
    "stock_diagnosis": ("search", "miaoxiang_search", "EM_API_KEY"),
    "fund_diagnosis": ("search", "miaoxiang_search", "EM_API_KEY"),
    "stock_market_hotspot_discovery": ("search", "miaoxiang_search", "EM_API_KEY"),
    "topic_research_report": ("search", "miaoxiang_search", "EM_API_KEY"),
    "industry_research_report": ("search", "miaoxiang_search", "EM_API_KEY"),
    "stock_earnings_review": ("search", "miaoxiang_search", "EM_API_KEY"),
    "mx_financial_assistant": ("search", "miaoxiang_search", "EM_API_KEY"),
    "hithink_astock_selector": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_basicinfo_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_business_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_event_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_finance_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_industry_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_insresearch_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_macro_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_management_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_market_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_sector_selector": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "hithink_zhishu_query": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "announcement_search": ("search", "iwencai_search", "IWENCAI_API_KEY"),
    "kimi_web_search": ("search", "kimi_search", "MOONSHOT_API_KEY"),
    "kimi_llm": ("llm", "kimi_llm", "MOONSHOT_API_KEY"),
    "deepseek_llm": ("llm", "deepseek_chat", None),
    "aliyun_coding_plan": ("llm", "aliyun_coding_plan", None),
    "volcengine_coding_plan": ("llm", "volcengine_coding_plan", None),
    "openai_compatible": ("llm", "openai_compatible", None),
}

STATUS_MAPPING = {
    "active": "active",
    "disabled": "disabled",
    "cooling_down": "cooldown",
    "invalid": "invalid",
}


@dataclass(frozen=True)
class LegacyKeyRow:
    old_key_id: int
    provider_code: str
    key_name: str
    encrypted_key: str
    secret_fingerprint: str | None
    priority: int
    weight: int
    status: str
    failure_count: int
    last_used_at: datetime | None
    cooldown_until: datetime | None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate legacy provider_key rows into t_config_value.")
    parser.add_argument("--apply", action="store_true", help="Write rows. Without this flag the script only prints a dry-run summary.")
    parser.add_argument("--verify-decrypt", action="store_true", help="Decrypt each legacy ciphertext and verify the stored fingerprint.")
    parser.add_argument("--include-llm", action="store_true", help="Also migrate legacy LLM provider keys when matching config nodes exist.")
    return parser.parse_args()


async def _table_exists(session, table_name: str) -> bool:
    return (await session.execute(text("select to_regclass(:table_name)"), {"table_name": table_name})).scalar_one() is not None


async def _load_legacy_keys(session) -> list[LegacyKeyRow]:
    rows = (
        await session.execute(
            text(
                """
                select
                    pk.id as old_key_id,
                    p.code as provider_code,
                    pk.key_name,
                    pk.encrypted_key,
                    pk.secret_fingerprint,
                    pk.priority,
                    pk.weight,
                    pk.status,
                    pk.failure_count,
                    pk.last_used_at,
                    pk.cooldown_until,
                    pk.is_enabled,
                    pk.created_at,
                    pk.updated_at
                from provider_key pk
                join provider p on p.id = pk.provider_id
                order by p.code, pk.id
                """
            )
        )
    ).mappings()
    return [LegacyKeyRow(**dict(row)) for row in rows]


async def _load_configs(session) -> dict[tuple[str, str], int]:
    rows = (
        await session.execute(
            text(
                """
                select id, category_code, config_code
                from t_system_config
                where is_enabled = true
                """
            )
        )
    ).mappings()
    return {(row["category_code"], row["config_code"]): row["id"] for row in rows}


async def _existing_old_key_ids(session) -> set[int]:
    rows = (
        await session.execute(
            text(
                """
                select (metadata->>'old_key_id')::bigint as old_key_id
                from t_config_value
                where metadata->>'migrated_from' = 'stock-analysis.provider_key'
                  and metadata ? 'old_key_id'
                """
            )
        )
    ).all()
    return {row[0] for row in rows if row[0] is not None}


def _verify_ciphertext(cipher: SecretCipher, row: LegacyKeyRow) -> tuple[bool, str | None, str | None]:
    try:
        secret = cipher.decrypt(row.encrypted_key)
    except Exception as exc:
        return False, None, f"decrypt_failed:{type(exc).__name__}"
    fingerprint = build_secret_fingerprint(secret)
    if row.secret_fingerprint and row.secret_fingerprint != fingerprint:
        return False, fingerprint, "fingerprint_mismatch"
    return True, fingerprint, None


def _target_for(row: LegacyKeyRow, *, include_llm: bool) -> tuple[str, str, str | None] | None:
    target = FAMILY_PROVIDER_MAPPING.get(row.provider_code)
    if target is None:
        return None
    if target[0] == "llm" and not include_llm:
        return None
    return target


async def _insert_config_value(session, row: LegacyKeyRow, *, target_config_id: int, env_var_name: str | None, fingerprint: str) -> None:
    await session.execute(
        text(
            """
            insert into t_config_value (
                system_config_id,
                value_name,
                value_kind,
                encrypted_value,
                fingerprint,
                priority,
                weight,
                status,
                failure_count,
                last_used_at,
                cooldown_until,
                is_enabled,
                description,
                metadata,
                created_at,
                updated_at
            )
            values (
                :system_config_id,
                :value_name,
                'api_key',
                :encrypted_value,
                :fingerprint,
                :priority,
                :weight,
                :status,
                :failure_count,
                :last_used_at,
                :cooldown_until,
                :is_enabled,
                :description,
                cast(:metadata_json as jsonb),
                :created_at,
                :updated_at
            )
            """
        ),
        {
            "system_config_id": target_config_id,
            "value_name": row.key_name,
            "encrypted_value": row.encrypted_key,
            "fingerprint": fingerprint,
            "priority": row.priority,
            "weight": row.weight,
            "status": STATUS_MAPPING.get(row.status, row.status),
            "failure_count": row.failure_count,
            "last_used_at": row.last_used_at,
            "cooldown_until": row.cooldown_until,
            "is_enabled": row.is_enabled,
            "description": f"migrated from legacy provider_key {row.provider_code}/{row.key_name}",
            "metadata_json": _json_dumps(
                {
                    "migrated_from": "stock-analysis.provider_key",
                    "old_table": "provider_key",
                    "old_key_id": row.old_key_id,
                    "old_provider_code": row.provider_code,
                    "old_env_var_name": env_var_name,
                }
            ),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        },
    )


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


async def main() -> None:
    args = _parse_args()
    maker = get_sessionmaker()
    cipher = SecretCipher(get_settings().config_master_key)
    async with maker() as session:
        for table_name in ("provider", "provider_key", "t_system_config", "t_config_value"):
            if not await _table_exists(session, table_name):
                raise SystemExit(f"required table does not exist: {table_name}")

        legacy_rows = await _load_legacy_keys(session)
        configs = await _load_configs(session)
        existing_old_ids = await _existing_old_key_ids(session)

        summary = {
            "legacy_total": len(legacy_rows),
            "planned": 0,
            "inserted": 0,
            "skipped_existing": 0,
            "skipped_unmapped": 0,
            "skipped_missing_node": 0,
            "verify_failed": 0,
        }
        details = []

        for row in legacy_rows:
            target = _target_for(row, include_llm=args.include_llm)
            if target is None:
                summary["skipped_unmapped"] += 1
                details.append((row.old_key_id, row.provider_code, "skip_unmapped_or_llm_disabled", None, row.secret_fingerprint))
                continue

            domain, node_code, env_var_name = target
            config_id = configs.get((domain, node_code))
            if config_id is None:
                summary["skipped_missing_node"] += 1
                details.append((row.old_key_id, row.provider_code, "skip_missing_node", f"{domain}/{node_code}", row.secret_fingerprint))
                continue

            if row.old_key_id in existing_old_ids:
                summary["skipped_existing"] += 1
                details.append((row.old_key_id, row.provider_code, "skip_existing", f"{domain}/{node_code}", row.secret_fingerprint))
                continue

            fingerprint = row.secret_fingerprint
            if args.verify_decrypt:
                ok, verified_fingerprint, error = _verify_ciphertext(cipher, row)
                if not ok:
                    summary["verify_failed"] += 1
                    details.append((row.old_key_id, row.provider_code, error, f"{domain}/{node_code}", row.secret_fingerprint))
                    continue
                fingerprint = verified_fingerprint

            if not fingerprint:
                summary["verify_failed"] += 1
                details.append((row.old_key_id, row.provider_code, "missing_fingerprint", f"{domain}/{node_code}", None))
                continue

            summary["planned"] += 1
            details.append((row.old_key_id, row.provider_code, "plan_insert" if not args.apply else "insert", f"{domain}/{node_code}", fingerprint))
            if args.apply:
                await _insert_config_value(session, row, target_config_id=config_id, env_var_name=env_var_name, fingerprint=fingerprint)
                summary["inserted"] += 1

        if args.apply:
            await session.commit()
        else:
            await session.rollback()

        print("mode", "apply" if args.apply else "dry-run")
        print("verify_decrypt", bool(args.verify_decrypt))
        print("include_llm", bool(args.include_llm))
        for key, value in summary.items():
            print(key, value)
        print("details")
        for old_key_id, provider_code, action, target, fingerprint in details:
            print(
                f"old_key_id={old_key_id} provider={provider_code} action={action} "
                f"target={target or '-'} fingerprint={fingerprint or '-'}"
            )


if __name__ == "__main__":
    asyncio.run(main())
