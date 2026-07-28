from __future__ import annotations

from app.modules.scheduler_center.validation import (
    CronValidationError,
    PayloadValidationError,
    normalize_crontab_for_apscheduler,
    validate_cron_expr,
    validate_payload,
)


SCHEMA = {
    "source": {"label": "数据源", "type": "string", "options": ["tushare", "akshare"], "required": True},
    "limit": {"label": "上限", "type": "number", "min": 1, "max": 20},
    "version_no": {"label": "版本号", "type": "integer", "min": 1, "max": 99},
    "enabled": {"label": "启用", "type": "boolean"},
    "types": {"label": "类型", "type": "array", "options": ["concept", "industry"]},
    "params": {"label": "附加参数", "type": "json"},
}


def test_cron_weekday_normalization_and_validation() -> None:
    assert normalize_crontab_for_apscheduler("20 8 * * 1-5") == "20 8 * * mon,tue,wed,thu,fri"
    validate_cron_expr("20 8 * * 1-5", timezone="Asia/Shanghai")
    validate_cron_expr(None, timezone="Asia/Shanghai")


def test_invalid_cron_is_rejected() -> None:
    try:
        validate_cron_expr("not a cron", timezone="Asia/Shanghai")
    except CronValidationError:
        pass
    else:
        raise AssertionError("invalid cron must fail")


def test_payload_validation_covers_types_ranges_and_unknowns() -> None:
    valid = {"source": "tushare", "limit": 10, "version_no": 1, "enabled": True, "types": ["concept"], "params": {"trade_date": "20260101"}}
    validate_payload(valid, SCHEMA)

    for invalid in (
        {**valid, "limit": 0},
        {**valid, "version_no": 1.5},
        {**valid, "version_no": True},
        {**valid, "source": "mootdx"},
        {**valid, "types": ["invalid"]},
        {**valid, "enabled": "true"},
        {**valid, "unknown": 1},
    ):
        try:
            validate_payload(invalid, SCHEMA)
        except PayloadValidationError:
            continue
        raise AssertionError(f"invalid payload was accepted: {invalid}")


def test_legacy_unknown_payload_key_can_be_preserved_but_not_added() -> None:
    validate_payload({"source": "tushare", "legacy": "keep"}, SCHEMA, allowed_unknown_keys={"legacy"})
    try:
        validate_payload({"source": "tushare", "unexpected": "reject"}, SCHEMA, allowed_unknown_keys={"legacy"})
    except PayloadValidationError:
        pass
    else:
        raise AssertionError("new unknown payload key must fail")
