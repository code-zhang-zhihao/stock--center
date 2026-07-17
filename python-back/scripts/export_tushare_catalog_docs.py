from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

from app.modules.market_data.tushare.catalog import TUSHARE_A_SHARE_CATALOG


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "providers" / "tushare"


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def render_category(category: str, specs) -> str:
    lines = [f"# Tushare `{category}`", "", "Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。", ""]
    for spec in sorted(specs, key=lambda item: item.api_name):
        lines.extend([
            f"## `{spec.api_name}`",
            "",
            f"- 官方文档：[doc_id={spec.doc_id}]({spec.doc_url})",
            f"- 积分门槛：`{spec.min_points if spec.min_points is not None else 'unknown'}`（{spec.point_status}）",
            f"- 当前状态：`{', '.join(sorted(spec.status))}`",
            "",
            "### 入参",
            "",
        ])
        params = [(f"`{item.name}`", item.value_type, "是" if item.required else "否", ", ".join(item.enum) or "-", item.description or "-") for item in spec.params]
        lines.extend(_table(("参数", "类型", "必填", "枚举", "说明"), params) if params else ["无"])
        lines.extend(["", "### 出参", ""])
        outputs = [(f"`{item.name}`", item.value_type, item.description or "-") for item in spec.fields]
        lines.extend(_table(("字段", "类型", "说明"), outputs) if outputs else ["该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。"])
        lines.extend(["", "### Raw 调用", "", "```python", "from app.modules.market_data.tushare.contracts import TushareApiRequest", "", f"response = await transport.request(TushareApiRequest(\"{spec.api_name}\", {spec.audit_params!r}))", "# response.records 保持 Tushare 原始字段", "```", ""])
    return "\n".join(lines)


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    categories = defaultdict(list)
    for spec in TUSHARE_A_SHARE_CATALOG.values():
        categories[spec.category].append(spec)
    readme = ["# Tushare Provider 契约", "", "本文档由 `python-back/scripts/export_tushare_catalog_docs.py` 自动生成。", "", "- Provider 只做参数校验、Token/URL 注入、HTTP 传输和原始响应解析。", "- `TushareApiResponse.records` 与上游字段一致，不包含 Canonical 字段。", "- `point_status=unknown` 或未列出出参字段的接口，不能被视为已完整审计。", "", "## 官方目录", ""]
    for category in sorted(categories):
        relative = Path(*category.split("."))
        destination = OUTPUT / f"{relative}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_category(category, categories[category]), encoding="utf-8")
        readme.append(f"- [{category}]({relative.as_posix()}.md)")
    (OUTPUT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
