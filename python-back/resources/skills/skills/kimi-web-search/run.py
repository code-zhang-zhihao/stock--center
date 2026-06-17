#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Kimi web_search fallback.")
    parser.add_argument("--query", required=True, help="Search query.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum result count hint.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    api_key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if not api_key:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": "provider_key_missing",
                    "error_message": "MOONSHOT_API_KEY is required.",
                    "results": [],
                },
                ensure_ascii=False,
            )
        )
        return 2

    api_url = os.environ.get("KIMI_API_URL", "https://api.moonshot.cn/v1/chat/completions")
    model = os.environ.get("KIMI_MODEL", "moonshot-v1-8k")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是A股信息检索助手。请使用可用的web_search能力检索最新公开信息，并返回JSON。",
            },
            {
                "role": "user",
                "content": (
                    "请检索以下A股相关问题，最多返回"
                    f"{args.limit}条高相关结果。每条包含title、url、source、published_at、summary。"
                    f"\n查询：{args.query}"
                ),
            },
        ],
        "tools": [{"type": "builtin_function", "function": {"name": "$web_search"}}],
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": "kimi_http_error",
                    "error_message": f"Kimi API returned HTTP {exc.code}.",
                    "raw": body[-4000:],
                    "results": [],
                },
                ensure_ascii=False,
            )
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": "kimi_request_failed",
                    "error_message": str(exc),
                    "results": [],
                },
                ensure_ascii=False,
            )
        )
        return 1

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": "kimi_invalid_json",
                    "error_message": "Kimi API response is not valid JSON.",
                    "raw": raw[-4000:],
                    "results": [],
                },
                ensure_ascii=False,
            )
        )
        return 1

    content = ""
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content") or ""

    print(
        json.dumps(
            {
                "success": True,
                "results": [
                    {
                        "title": "Kimi web_search result",
                        "summary": content,
                        "content": content,
                        "source": "kimi_web_search",
                        "url": None,
                    }
                ]
                if content
                else [],
                "raw": data,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
