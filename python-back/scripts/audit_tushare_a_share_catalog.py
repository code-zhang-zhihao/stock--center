from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import get_sessionmaker
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.tushare.catalog import TUSHARE_A_SHARE_CATALOG
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.market_data.tushare_runtime import TushareProviderFactory


def _status(error: Exception) -> str:
    text = str(error).lower()
    if "permission" in text or "积分" in text or "权限" in text:
        return "permission_denied"
    if "rate" in text or "频率" in text or "限频" in text:
        return "rate_limited"
    if "transport" in text or "connection" in text or "timeout" in text:
        return "transport_error"
    return "unsupported"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Audit catalogued Tushare Pro A-share APIs using the configured Token pool.")
    parser.add_argument("--api", action="append", choices=sorted(TUSHARE_A_SHARE_CATALOG))
    parser.add_argument("--category", action="append", help="Catalog category, such as stock.fund_flow or index.market")
    parser.add_argument("--family", action="append", help="Compatibility alias for --category")
    parser.add_argument("--all", action="store_true", help="Audit the full A-share catalog.")
    args = parser.parse_args()
    categories = set((args.category or []) + (args.family or []))
    selected = [spec for spec in TUSHARE_A_SHARE_CATALOG.values() if (not args.api or spec.api_name in args.api) and (not categories or spec.category in categories)]
    if not selected or (not args.all and not args.api and not categories):
        parser.error("pass --all, --api, --category, or --family")

    results: list[dict] = []
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        factory = TushareProviderFactory(ConfigCenterRepository(session))
        for spec in selected:
            try:
                response = await factory.call(
                    f"tushare_catalog_audit:{spec.api_name}",
                    lambda provider, spec=spec: provider.request(TushareApiRequest(spec.api_name, dict(spec.audit_params))),
                    request_summary={"audit": True, "api_name": spec.api_name, "params": spec.audit_params},
                    execution_mode="scheduler",
                )
                results.append({"api_name": spec.api_name, "category": spec.category, "min_points": spec.min_points, "point_status": spec.point_status, "status": "available", "row_count": response.row_count, "token_fingerprint": response.token_fingerprint, "endpoint_url": response.endpoint_url, "doc_url": spec.doc_url})
            except Exception as exc:  # One bad API must not stop a full audit.
                results.append({"api_name": spec.api_name, "category": spec.category, "min_points": spec.min_points, "point_status": spec.point_status, "status": _status(exc), "error": str(exc), "doc_url": spec.doc_url})
    report = {"scope": "tushare_pro_a_share", "generated_at": datetime.now(timezone.utc).isoformat(), "count": len(results), "results": results}
    report_dir = ROOT / "data" / "audits"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"tushare-a-share-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "report_path": str(report_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
