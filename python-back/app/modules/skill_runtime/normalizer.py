from app.modules.skill_runtime.schemas import SkillRunResult


def normalize_skill_result(result: SkillRunResult) -> dict:
    payload = result.stdout_json
    if isinstance(payload, dict):
        normalized = _normalize_dict_payload(payload)
    elif isinstance(payload, list):
        normalized = {"items": payload, "item_count": len(payload)}
    else:
        normalized = {"text": result.stdout_text or "", "item_count": 1 if result.stdout_text else 0}
    normalized["file_count"] = len(result.files)
    return normalized


def result_item_count(result: SkillRunResult) -> int:
    normalized = result.normalized or normalize_skill_result(result)
    for key in ("item_count", "code_count"):
        value = normalized.get(key)
        if isinstance(value, int):
            return value
    items = normalized.get("items")
    if isinstance(items, list):
        return len(items)
    return 1 if result.success else 0


def _normalize_dict_payload(payload: dict) -> dict:
    if isinstance(payload.get("datas"), list):
        return {
            "source_shape": "hithink",
            "items": payload.get("datas") or [],
            "item_count": len(payload.get("datas") or []),
            "code_count": _int_or_none(payload.get("code_count")),
            "trace_id": payload.get("trace_id"),
        }
    if isinstance(payload.get("data"), list):
        return {
            "source_shape": "list_data",
            "items": payload.get("data") or [],
            "item_count": len(payload.get("data") or []),
            "trace_id": payload.get("trace_id"),
        }
    if any(key in payload for key in ("content", "raw", "output_path")):
        raw = payload.get("raw")
        return {
            "source_shape": "miaoxiang",
            "content": payload.get("content"),
            "raw_present": raw is not None,
            "output_path": payload.get("output_path"),
            "item_count": 1 if payload.get("content") or raw else 0,
        }
    return {"source_shape": "generic_json", "payload": payload, "item_count": 1 if payload else 0}


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
