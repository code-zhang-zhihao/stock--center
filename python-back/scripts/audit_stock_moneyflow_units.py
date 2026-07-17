from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.db.session import get_sessionmaker


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit t_stock_fund_flow_daily unit normalization status.")
    parser.add_argument("--sample-limit", type=int, default=10, help="Number of sample rows to print per bucket.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a human-readable report.")
    return parser.parse_args()


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


async def _bucket_summary(session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                select
                    case
                        when source = 'tushare:moneyflow'
                         and coalesce(metadata->>'unit_normalized', '') = 'yuan'
                            then 'normalized_yuan'
                        when source = 'tushare:moneyflow'
                         and coalesce(metadata#>>'{unit_conversions,moneyflow.*_amount}', '') = 'ten_thousand_yuan -> yuan'
                            then 'adapter_yuan_missing_marker'
                        when source = 'tushare:moneyflow'
                            then 'legacy_ten_thousand_yuan_candidate'
                        else 'other_source'
                    end as bucket,
                    count(*) as row_count,
                    min(trade_date) as min_trade_date,
                    max(trade_date) as max_trade_date,
                    min(main_net_inflow) as min_main_net_inflow,
                    max(main_net_inflow) as max_main_net_inflow,
                    percentile_cont(0.5) within group (order by abs(coalesce(main_net_inflow, 0))) as median_abs_main_net_inflow
                from t_stock_fund_flow_daily
                group by 1
                order by 1
                """
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def _samples(session, bucket: str, limit: int) -> list[dict[str, Any]]:
    condition = {
        "normalized_yuan": """
            source = 'tushare:moneyflow'
            and coalesce(metadata->>'unit_normalized', '') = 'yuan'
        """,
        "adapter_yuan_missing_marker": """
            source = 'tushare:moneyflow'
            and coalesce(metadata->>'unit_normalized', '') <> 'yuan'
            and coalesce(metadata#>>'{unit_conversions,moneyflow.*_amount}', '') = 'ten_thousand_yuan -> yuan'
        """,
        "legacy_ten_thousand_yuan_candidate": """
            source = 'tushare:moneyflow'
            and coalesce(metadata->>'unit_normalized', '') <> 'yuan'
            and coalesce(metadata#>>'{unit_conversions,moneyflow.*_amount}', '') <> 'ten_thousand_yuan -> yuan'
        """,
    }.get(bucket)
    if not condition:
        return []
    rows = (
        await session.execute(
            text(
                f"""
                select
                    stock_code,
                    trade_date,
                    source,
                    main_net_inflow,
                    big_order_net_inflow,
                    super_large_net_inflow,
                    metadata->>'unit_normalized' as unit_normalized,
                    metadata#>>'{{unit_conversions,moneyflow.*_amount}}' as amount_conversion
                from t_stock_fund_flow_daily
                where {condition}
                order by trade_date desc, stock_code
                limit :limit
                """
            ),
            {"limit": max(limit, 0)},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def main() -> int:
    args = _parse_args()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        summary = await _bucket_summary(session)
        sample_buckets = [
            "legacy_ten_thousand_yuan_candidate",
            "adapter_yuan_missing_marker",
            "normalized_yuan",
        ]
        samples = {bucket: await _samples(session, bucket, args.sample_limit) for bucket in sample_buckets}
    result = {"summary": summary, "samples": samples}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
        return 0

    print("Stock moneyflow unit audit")
    print("==========================")
    for row in summary:
        print(
            f"- {row['bucket']}: rows={row['row_count']} "
            f"date_range={_json_default(row['min_trade_date'])}..{_json_default(row['max_trade_date'])} "
            f"main_net_abs_median={_json_default(row['median_abs_main_net_inflow'])}"
        )
    print("")
    for bucket, rows in samples.items():
        print(f"[{bucket}] samples={len(rows)}")
        for row in rows:
            print(
                f"  {row['trade_date']} {row['stock_code']} main={row['main_net_inflow']} "
                f"big={row['big_order_net_inflow']} super={row['super_large_net_inflow']} "
                f"unit={row['unit_normalized']} conversion={row['amount_conversion']}"
            )
        print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
