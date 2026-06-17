from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import get_settings


@dataclass(frozen=True)
class SkillSpec:
    code: str
    display_name: str
    family: str
    capabilities: tuple[str, ...]
    entrypoint: str
    runtime: str = "python"
    args_style: str = "positional"
    key_env: str | None = None
    timeout_seconds: int | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)


class SkillRegistry:
    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self.root = root or Path(settings.skill_root).resolve()
        self._skills = {skill.code: skill for skill in self._build_specs()}

    def list(self) -> list[SkillSpec]:
        return list(self._skills.values())

    def get(self, skill_code: str) -> SkillSpec | None:
        return self._skills.get(skill_code)

    def require(self, skill_code: str) -> SkillSpec:
        skill = self.get(skill_code)
        if skill is None:
            raise KeyError(f"skill not found: {skill_code}")
        return skill

    def by_capability(self, capability: str) -> list[SkillSpec]:
        return [skill for skill in self._skills.values() if capability in skill.capabilities]

    def by_family(self, family: str) -> list[SkillSpec]:
        return [skill for skill in self._skills.values() if skill.family == family]

    def entrypoint_path(self, skill: SkillSpec) -> Path:
        return self.root / skill.entrypoint

    def _build_specs(self) -> list[SkillSpec]:
        return [
            SkillSpec("mx_finance_search", "妙想金融资讯搜索", "miaoxiang", ("news_search", "announcement_search", "report_search", "topic_research"), "mx-skills/mx-finance-search/scripts/get_data.py", key_env="EM_API_KEY"),
            SkillSpec("mx_finance_data", "妙想金融数据查询", "miaoxiang", ("finance_data_query", "market_data_query"), "mx-skills/mx-finance-data/scripts/get_data.py", args_style="query_option", key_env="EM_API_KEY"),
            SkillSpec("mx_macro_data", "妙想宏观数据查询", "miaoxiang", ("macro_query",), "mx-skills/mx-macro-data/scripts/get_data.py", args_style="query_option", key_env="EM_API_KEY"),
            SkillSpec("mx_stocks_screener", "妙想智能选股", "miaoxiang", ("stock_screening",), "mx-skills/mx-stocks-screener/scripts/get_data.py", args_style="query_option", key_env="EM_API_KEY"),
            SkillSpec("stock_diagnosis", "妙想个股诊断", "miaoxiang", ("stock_diagnosis",), "mx-skills/stock-diagnosis/scripts/get_data.py", key_env="EM_API_KEY"),
            SkillSpec("fund_diagnosis", "妙想基金诊断", "miaoxiang", ("fund_query", "fund_diagnosis"), "mx-skills/fund-diagnosis/scripts/get_data.py", key_env="EM_API_KEY"),
            SkillSpec("stock_market_hotspot_discovery", "妙想市场热点发现", "miaoxiang", ("hotspot_discovery",), "mx-skills/stock-market-hotspot-discovery/scripts/get_data.py", key_env="EM_API_KEY"),
            SkillSpec("topic_research_report", "妙想主题研究", "miaoxiang", ("topic_research",), "mx-skills/topic-research-report/scripts/get_data.py", key_env="EM_API_KEY"),
            SkillSpec("industry_research_report", "妙想行业研究", "miaoxiang", ("industry_query",), "mx-skills/industry-research-report/scripts/get_data.py", args_style="query_option", key_env="EM_API_KEY"),
            SkillSpec("stock_earnings_review", "妙想财报复盘", "miaoxiang", ("earnings_review",), "mx-skills/stock-earnings-review/scripts/call_review_api.py", args_style="earnings_review_cli", key_env="EM_API_KEY"),
            SkillSpec("mx_financial_assistant", "妙想金融助手", "miaoxiang", ("assistant_query",), "mx-skills/mx-financial-assistant/scripts/generate_answer.py", args_style="query_option", key_env="EM_API_KEY"),
            SkillSpec("hithink_astock_selector", "问财 A 股选股", "hithink", ("stock_screening",), "skills/hithink-astock-selector/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_basicinfo_query", "问财基础信息", "hithink", ("basic_info_query",), "skills/hithink-basicinfo-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_business_query", "问财经营数据", "hithink", ("business_query",), "skills/hithink-business-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_event_query", "问财事件数据", "hithink", ("event_search",), "skills/hithink-event-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_finance_query", "问财财务数据", "hithink", ("finance_data_query",), "skills/hithink-finance-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_industry_query", "问财行业数据", "hithink", ("industry_query",), "skills/hithink-industry-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_insresearch_query", "问财机构研究", "hithink", ("report_search",), "skills/hithink-insresearch-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_macro_query", "问财宏观数据", "hithink", ("macro_query",), "skills/hithink-macro-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_management_query", "问财股东管理", "hithink", ("management_query",), "skills/hithink-management-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_market_query", "问财行情技术", "hithink", ("market_data_query",), "skills/hithink-market-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_sector_selector", "问财板块筛选", "hithink", ("industry_query", "stock_screening"), "skills/hithink-sector-selector/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("hithink_zhishu_query", "问财指数数据", "hithink", ("index_query",), "skills/hithink-zhishu-query/scripts/cli.py", args_style="hithink_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("announcement_search", "问财公告搜索", "hithink", ("announcement_search",), "skills/announcement-search/scripts/__main__.py", args_style="announcement_cli", key_env="IWENCAI_API_KEY"),
            SkillSpec("news_search", "通用新闻搜索", "generic", ("news_search",), "skills/news-search/scripts/news-search.js", runtime="node", args_style="news_cli", timeout_seconds=90),
            SkillSpec("report_search", "研报搜索", "generic", ("report_search",), "skills/report-search/scripts/search_reports.py", args_style="report_cli"),
            SkillSpec("kimi_web_search", "Kimi Web Search", "kimi", ("web_search_fallback", "news_search", "announcement_search", "event_search", "report_search", "macro_query", "industry_query", "business_query", "management_query", "hotspot_discovery", "topic_research"), "skills/kimi-web-search/run.py", args_style="query_option", key_env="MOONSHOT_API_KEY"),
        ]
