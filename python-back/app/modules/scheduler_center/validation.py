import json
from collections.abc import Iterable
from zoneinfo import ZoneInfo


_CRONTAB_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


class CronValidationError(ValueError):
    pass


class PayloadValidationError(ValueError):
    pass


def _map_crontab_weekday(value: int) -> str:
    if value == 7:
        value = 0
    if value < 0 or value > 6:
        raise CronValidationError("Cron 星期字段只能使用 0-7")
    return _CRONTAB_DOW_NAMES[value]


def _expand_crontab_weekday_range(start: int, end: int, step: int = 1) -> list[str]:
    if start == 7:
        start = 0
    if end == 7:
        end = 0
    if start < 0 or start > 6 or end < 0 or end > 6:
        raise CronValidationError("Cron 星期字段只能使用 0-7")
    values = list(range(start, end + 1)) if start <= end else [*range(start, 7), *range(0, end + 1)]
    return [_map_crontab_weekday(value) for value in values[::step]]


def _normalize_crontab_weekday_token(token: str) -> str:
    if not token or any(char.isalpha() for char in token):
        return token
    base, separator, step_text = token.partition("/")
    if separator and (not step_text.isdigit() or int(step_text) <= 0):
        raise CronValidationError("Cron 星期步长必须是正整数")
    step = int(step_text) if separator else 1
    if base == "*":
        return token
    if "-" in base:
        start_text, end_text = base.split("-", 1)
        if start_text.isdigit() and end_text.isdigit():
            return ",".join(_expand_crontab_weekday_range(int(start_text), int(end_text), step))
        return token
    if base.isdigit():
        return _map_crontab_weekday(int(base))
    return token


def normalize_crontab_for_apscheduler(cron_expr: str) -> str:
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr
    weekday = parts[4]
    if weekday not in {"*", "?"}:
        parts[4] = ",".join(_normalize_crontab_weekday_token(token) for token in weekday.split(","))
    return " ".join(parts)


def validate_cron_expr(cron_expr: str | None, *, timezone: str) -> None:
    if timezone != "Asia/Shanghai":
        raise CronValidationError("当前调度中心只支持 Asia/Shanghai 时区")
    if cron_expr is None:
        return
    try:
        from apscheduler.triggers.cron import CronTrigger

        CronTrigger.from_crontab(normalize_crontab_for_apscheduler(cron_expr), timezone=ZoneInfo(timezone))
    except CronValidationError:
        raise
    except Exception as exc:
        raise CronValidationError(f"无效的五段 Cron 表达式: {cron_expr}") from exc


def validate_payload(
    payload: dict,
    parameter_schema: dict,
    *,
    allowed_unknown_keys: Iterable[str] = (),
) -> None:
    schema = parameter_schema or {}
    allowed_unknown = set(allowed_unknown_keys)
    unknown_keys = sorted(set(payload) - set(schema) - allowed_unknown)
    if unknown_keys:
        raise PayloadValidationError(f"存在未定义的参数: {', '.join(unknown_keys)}")

    for key, definition in schema.items():
        spec = definition if isinstance(definition, dict) else {}
        present = key in payload and payload[key] is not None
        if spec.get("required") and not present:
            raise PayloadValidationError(f"参数 {spec.get('label') or key} 为必填项")
        if not present:
            continue
        _validate_payload_value(key, payload[key], spec)


def _validate_payload_value(key: str, value: object, spec: dict) -> None:
    label = str(spec.get("label") or key)
    value_type = str(spec.get("type") or "string")
    options = spec.get("options")

    if value_type == "string":
        if not isinstance(value, str):
            raise PayloadValidationError(f"参数 {label} 必须是文本")
        if isinstance(options, list) and value not in options:
            raise PayloadValidationError(f"参数 {label} 不在允许选项中")
        return

    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PayloadValidationError(f"参数 {label} 必须是数字")
        _validate_number_range(label, float(value), spec)
        return

    if value_type == "boolean":
        if not isinstance(value, bool):
            raise PayloadValidationError(f"参数 {label} 必须是布尔值")
        return

    if value_type == "array":
        if not isinstance(value, list):
            raise PayloadValidationError(f"参数 {label} 必须是数组")
        if isinstance(options, list) and any(item not in options for item in value):
            raise PayloadValidationError(f"参数 {label} 包含不允许的选项")
        return

    if value_type == "json":
        try:
            json.dumps(value, ensure_ascii=True)
        except (TypeError, ValueError) as exc:
            raise PayloadValidationError(f"参数 {label} 必须是有效 JSON") from exc
        return

    raise PayloadValidationError(f"参数 {label} 使用了不支持的类型: {value_type}")


def _validate_number_range(label: str, value: float, spec: dict) -> None:
    minimum = spec.get("min")
    maximum = spec.get("max")
    if minimum is not None and value < float(minimum):
        raise PayloadValidationError(f"参数 {label} 不能小于 {minimum}")
    if maximum is not None and value > float(maximum):
        raise PayloadValidationError(f"参数 {label} 不能大于 {maximum}")
