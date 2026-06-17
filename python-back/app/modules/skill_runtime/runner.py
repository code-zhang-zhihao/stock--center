import asyncio
import json
import os
import sys
from pathlib import Path
from time import perf_counter

from app.core.config import get_settings
from app.modules.skill_runtime.normalizer import normalize_skill_result
from app.modules.skill_runtime.registry import SkillRegistry, SkillSpec
from app.modules.skill_runtime.schemas import SkillCredential, SkillRunFile, SkillRunRequest, SkillRunResult


class SkillRunner:
    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or SkillRegistry()
        self.settings = get_settings()
        self.output_root = Path(self.settings.skill_output_dir).resolve()

    async def run(
        self,
        skill_code: str,
        payload: SkillRunRequest,
        *,
        trace_id: str,
        credential: SkillCredential | None = None,
    ) -> SkillRunResult:
        skill = self.registry.get(skill_code)
        if skill is None:
            return self._failed(skill_code, trace_id, payload.query, "skill_not_found", f"skill not found: {skill_code}")
        if skill.key_env and (not credential or not credential.secret_value):
            return self._failed(skill.code, trace_id, payload.query, "skill_key_missing", f"{skill.key_env} is required for {skill.code}")

        entrypoint = self.registry.entrypoint_path(skill)
        if not entrypoint.exists():
            return self._failed(skill.code, trace_id, payload.query, "skill_entrypoint_missing", str(entrypoint))

        run_dir = self.output_root / skill.code / trace_id
        run_dir.mkdir(parents=True, exist_ok=True)
        command = self._build_command(skill, entrypoint, payload)
        env = self._build_env(skill, credential, run_dir, payload)
        started = perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(run_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=payload.timeout_seconds or skill.timeout_seconds or self.settings.skill_default_timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            result = self._failed(skill.code, trace_id, payload.query, "skill_timeout", "skill process timed out")
            result.latency_ms = int((perf_counter() - started) * 1000)
            result.raw_stdout = self._redact(stdout_bytes.decode("utf-8", errors="replace"), credential)[-10000:] or None
            result.raw_stderr = self._redact(stderr_bytes.decode("utf-8", errors="replace"), credential)[-10000:] or None
            self._write_result(run_dir, result)
            return result

        stdout = self._redact(stdout_bytes.decode("utf-8", errors="replace"), credential)
        stderr = self._redact(stderr_bytes.decode("utf-8", errors="replace"), credential)
        stdout_json = self._parse_json(stdout)
        files = self._collect_files(run_dir)
        success = proc.returncode == 0 and (stdout_json is not None or bool(stdout.strip()) or bool(files))
        result = SkillRunResult(
            success=success,
            skill_code=skill.code,
            trace_id=trace_id,
            query=payload.query,
            exit_code=proc.returncode,
            latency_ms=int((perf_counter() - started) * 1000),
            stdout_json=stdout_json,
            stdout_text=None if stdout_json is not None else stdout.strip() or None,
            files=files,
            error_code=None if success else "skill_failed",
            error_message=None if success else (stderr.strip() or stdout.strip() or "skill process failed")[:1000],
            raw_stdout=stdout[-10000:] if stdout else None,
            raw_stderr=stderr[-10000:] if stderr else None,
        )
        result.normalized = normalize_skill_result(result)
        self._write_result(run_dir, result)
        return result

    def _build_command(self, skill: SkillSpec, entrypoint: Path, payload: SkillRunRequest) -> list[str]:
        if skill.runtime == "node":
            return ["node", str(entrypoint), payload.query, f"--max={payload.limit}", "--format=json", *skill.extra_args]

        base = [sys.executable, str(entrypoint)]
        if skill.args_style == "query_option":
            if skill.code == "mx_stocks_screener":
                extra = payload.extra or {}
                return [
                    *base,
                    "--query",
                    payload.query,
                    "--select-type",
                    str(extra.get("select_type") or extra.get("selectType") or "A股"),
                    *skill.extra_args,
                ]
            return [*base, "--query", payload.query, *skill.extra_args]
        if skill.args_style == "hithink_cli":
            return [*base, "--query", payload.query, "--page", str(payload.page), "--limit", str(payload.limit), *skill.extra_args]
        if skill.args_style == "announcement_cli":
            return [*base, payload.query, "--limit", str(payload.limit), "--format", "json", *skill.extra_args]
        if skill.args_style == "report_cli":
            return [*base, payload.query, "--size", str(payload.limit), "--json", *skill.extra_args]
        if skill.args_style == "earnings_review_cli":
            extra = payload.extra or {}
            stock_code = self._first_stock_code(payload.query)
            secu_code = str(extra.get("secu_code") or stock_code or "")
            return [
                *base,
                "--secu-code",
                secu_code,
                "--market-char",
                str(extra.get("market_char") or self._infer_market_char(secu_code)),
                "--class-code",
                str(extra.get("class_code") or "A"),
                "--report-date",
                str(extra.get("report_date") or extra.get("date") or ""),
                *skill.extra_args,
            ]
        return [*base, payload.query, *skill.extra_args]

    def _build_env(
        self,
        skill: SkillSpec,
        credential: SkillCredential | None,
        run_dir: Path,
        payload: SkillRunRequest,
    ) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["SKILL_TRACE_OUTPUT_DIR"] = str(run_dir)
        env["PATH"] = os.environ.get("PATH", "")
        provider_config = (payload.extra or {}).get("provider_config") if isinstance(payload.extra, dict) else {}
        if isinstance(provider_config, dict) and skill.code == "kimi_web_search":
            if provider_config.get("model"):
                env["KIMI_MODEL"] = str(provider_config["model"])
            if provider_config.get("api_url"):
                env["KIMI_API_URL"] = str(provider_config["api_url"])
        if skill.key_env and credential and credential.secret_value:
            env[skill.key_env] = credential.secret_value
        return env

    def _parse_json(self, text: str) -> dict | list | None:
        stripped = text.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            start_positions = [pos for pos in (stripped.find("{"), stripped.find("[")) if pos >= 0]
            if not start_positions:
                return None
            candidate = stripped[min(start_positions):]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return None

    def _collect_files(self, run_dir: Path) -> list[SkillRunFile]:
        files: list[SkillRunFile] = []
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file() or path.name == "skill-result.json":
                continue
            files.append(SkillRunFile(path=str(path), name=path.name, size=path.stat().st_size, content_type=self._guess_content_type(path)))
        return files

    def _guess_content_type(self, path: Path) -> str | None:
        return {
            ".json": "application/json",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }.get(path.suffix.lower())

    def _write_result(self, run_dir: Path, result: SkillRunResult) -> None:
        result_path = run_dir / "skill-result.json"
        result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    def _failed(self, skill_code: str, trace_id: str, query: str, code: str, message: str) -> SkillRunResult:
        return SkillRunResult(success=False, skill_code=skill_code, trace_id=trace_id, query=query, error_code=code, error_message=message)

    def _redact(self, text: str, credential: SkillCredential | None) -> str:
        if credential and credential.secret_value:
            return text.replace(credential.secret_value, "***REDACTED***")
        return text

    def _first_stock_code(self, text: str) -> str | None:
        for part in text.replace(",", " ").split():
            if part.isdigit() and len(part) == 6:
                return part
        return None

    def _infer_market_char(self, stock_code: str) -> str:
        if stock_code.startswith("6"):
            return "SH"
        if stock_code.startswith(("0", "3")):
            return "SZ"
        return ""
