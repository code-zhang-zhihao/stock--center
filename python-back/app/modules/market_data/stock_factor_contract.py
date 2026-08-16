"""Typed contract for the one official stock daily factor table.

``stk_factor_pro`` remains the preferred provider for advanced indicators, but
its QFQ fields are mapped directly into ``t_stock_factor_daily``.  Keeping the
mapping in one place prevents the close pipeline and historical backfill from
drifting back to opaque JSON archives.
"""

from __future__ import annotations

from typing import Any

from app.modules.market_data.providers import normalize_symbol, parse_date, safe_float, safe_int


# Provider field -> canonical typed column.  BFQ/HFQ fields are deliberately
# excluded: BFQ belongs to t_daily_bar and HFQ is derived from adjustment facts.
STK_FACTOR_PRO_QFQ_COLUMNS: dict[str, str] = {
    "open_qfq": "open_qfq",
    "high_qfq": "high_qfq",
    "low_qfq": "low_qfq",
    "close_qfq": "close_qfq",
    "ma_qfq_5": "ma5",
    "ma_qfq_10": "ma10",
    "ma_qfq_20": "ma20",
    "ma_qfq_30": "ma30",
    "ma_qfq_60": "ma60",
    "ma_qfq_90": "ma90",
    "ma_qfq_250": "ma250",
    "ema_qfq_5": "ema5",
    "ema_qfq_10": "ema10",
    "ema_qfq_20": "ema20",
    "ema_qfq_30": "ema30",
    "ema_qfq_60": "ema60",
    "ema_qfq_90": "ema90",
    "ema_qfq_250": "ema250",
    "macd_qfq": "macd",
    "macd_dif_qfq": "macd_dif",
    "macd_dea_qfq": "macd_dea",
    "kdj_qfq": "kdj_j",
    "kdj_k_qfq": "kdj_k",
    "kdj_d_qfq": "kdj_d",
    "rsi_qfq_6": "rsi6",
    "rsi_qfq_12": "rsi12",
    "rsi_qfq_24": "rsi24",
    "boll_upper_qfq": "boll_upper",
    "boll_mid_qfq": "boll_mid",
    "boll_lower_qfq": "boll_lower",
    "atr_qfq": "atr",
    "bbi_qfq": "bbi",
    "bias1_qfq": "bias1",
    "bias2_qfq": "bias2",
    "bias3_qfq": "bias3",
    "cci_qfq": "cci",
    "vr_qfq": "vr",
    "wr_qfq": "wr",
    "wr1_qfq": "wr1",
    "obv_qfq": "obv",
    "mfi_qfq": "mfi",
    "roc_qfq": "roc",
    "mtm_qfq": "mtm",
    "mtmma_qfq": "mtmma",
    "asi_qfq": "asi",
    "asit_qfq": "asit",
    "brar_ar_qfq": "brar_ar",
    "brar_br_qfq": "brar_br",
    "cr_qfq": "cr",
    "dfma_dif_qfq": "dfma_dif",
    "dfma_difma_qfq": "dfma_difma",
    "dmi_adx_qfq": "dmi_adx",
    "dmi_adxr_qfq": "dmi_adxr",
    "dmi_mdi_qfq": "dmi_mdi",
    "dmi_pdi_qfq": "dmi_pdi",
    "dpo_qfq": "dpo",
    "madpo_qfq": "madpo",
    "emv_qfq": "emv",
    "maemv_qfq": "maemv",
    "expma_12_qfq": "expma12",
    "expma_50_qfq": "expma50",
    "ktn_down_qfq": "keltner_lower",
    "ktn_mid_qfq": "keltner_mid",
    "ktn_upper_qfq": "keltner_upper",
    "mass_qfq": "mass",
    "ma_mass_qfq": "ma_mass",
    "maroc_qfq": "maroc",
    "psy_qfq": "psy",
    "psyma_qfq": "psyma",
    "taq_down_qfq": "taq_lower",
    "taq_mid_qfq": "taq_mid",
    "taq_up_qfq": "taq_upper",
    "trix_qfq": "trix",
    "trma_qfq": "trma",
    "xsii_td1_qfq": "xsii_td1",
    "xsii_td2_qfq": "xsii_td2",
    "xsii_td3_qfq": "xsii_td3",
    "xsii_td4_qfq": "xsii_td4",
}

STK_FACTOR_PRO_COUNT_COLUMNS = ("updays", "downdays", "topdays", "lowdays")

STK_FACTOR_PRO_CORE_COLUMNS = (
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "ma5",
    "ma10",
    "ma20",
    "ma30",
    "ma60",
    "ema5",
    "ema10",
    "ema20",
    "macd",
    "macd_dif",
    "macd_dea",
    "kdj_j",
    "kdj_k",
    "kdj_d",
    "rsi6",
    "rsi12",
    "rsi24",
    "boll_upper",
    "boll_mid",
    "boll_lower",
    "atr",
)


def map_stk_factor_pro_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Map one provider row without retaining its response body."""

    stock_code = normalize_symbol(str(record.get("ts_code") or ""))
    trade_date = parse_date(record.get("trade_date"))
    if not stock_code or trade_date is None:
        return None

    row: dict[str, Any] = {
        "stock_code": stock_code,
        "trade_date": trade_date,
        "price_basis": "qfq",
        "price_source": "tushare:stk_factor_pro",
        "technical_source": "tushare:stk_factor_pro",
        "calculation_revision": "technical_pro_only",
    }
    for provider_field, canonical_field in STK_FACTOR_PRO_QFQ_COLUMNS.items():
        row[canonical_field] = safe_float(record.get(provider_field))
    for field in STK_FACTOR_PRO_COUNT_COLUMNS:
        row[field] = safe_int(record.get(field))

    core_ready = all(row.get(field) is not None for field in STK_FACTOR_PRO_CORE_COLUMNS)
    extended_fields = set(STK_FACTOR_PRO_QFQ_COLUMNS.values()) - set(STK_FACTOR_PRO_CORE_COLUMNS)
    extended_ready = all(row.get(field) is not None for field in extended_fields)
    row["price_status"] = "ready" if all(row.get(field) is not None for field in ("open_qfq", "high_qfq", "low_qfq", "close_qfq")) else "partial"
    row["technical_core_status"] = "ready" if core_ready else "partial"
    row["technical_extended_status"] = "ready" if extended_ready else "partial"
    missing_groups = []
    if row["price_status"] != "ready":
        missing_groups.append("price")
    if not core_ready:
        missing_groups.append("technical_core")
    if not extended_ready:
        missing_groups.append("technical_extended")
    row["quality_flags"] = missing_groups
    return row
