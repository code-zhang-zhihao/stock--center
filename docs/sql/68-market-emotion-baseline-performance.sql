-- V2 情绪模型基线性能与市场级北向资金流历史补数。
-- Safe to re-run. Requires 59 (scheduler tags) and 67 (V2 emotion tables).

BEGIN;

INSERT INTO t_scheduler_job (
    job_code, job_name, job_type, description, parameter_schema,
    trigger_type, cron_expr, timezone, default_payload, max_instances,
    misfire_grace_seconds, timeout_seconds, retry_count, retry_interval_seconds,
    is_enabled, is_system, is_hidden, metadata
)
VALUES (
    'backfill_market_north_flow',
    '历史市场级北向资金流回填',
    'market_data',
    '按交易日窗口调用 Tushare moneyflow_hsgt，写入 t_market_north_flow_daily。默认补最近 250 个已有个股日线的交易日，为 V2 情绪模型基线提供可比的北向资金流输入；不回填北向持仓或两融。',
    '{
      "start_date":{"label":"开始日期","type":"string","required":false,"description":"与结束日期一起指定精确区间；为空时按最近已有个股日线向前取交易日数。"},
      "end_date":{"label":"结束日期","type":"string","required":false,"description":"为空时使用最近已有个股日线交易日。"},
      "trade_days":{"label":"回填交易日数","type":"number","default":250,"required":false,"min":60,"max":1000,"description":"未指定开始日期时回填最近多少个已有个股日线交易日。"},
      "only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false,"description":"跳过 north_money 已完整的日期；空值仍会重新请求。"},
      "request_window_trade_days":{"label":"单次请求交易日数","type":"number","default":120,"required":false,"min":20,"max":250,"description":"moneyflow_hsgt 每次日期区间的交易日数；默认 250 日约 3 次请求。"},
      "fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false,"description":"关闭时单个窗口失败会记录并继续，之后可 append_safe 重跑。"}
    }'::jsonb,
    'cron', NULL, 'Asia/Shanghai',
    '{"start_date":null,"end_date":null,"trade_days":250,"only_missing":true,"request_window_trade_days":120,"fail_fast":false}'::jsonb,
    1, 300, 1800, 1, 300,
    FALSE, TRUE, FALSE,
    '{"source":"68-market-emotion-baseline-performance.sql","manual_first":true,"writes":["t_market_north_flow_daily"],"provider":"tushare:moneyflow_hsgt"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    timezone = EXCLUDED.timezone,
    default_payload = EXCLUDED.default_payload,
    timeout_seconds = EXCLUDED.timeout_seconds,
    retry_count = EXCLUDED.retry_count,
    retry_interval_seconds = EXCLUDED.retry_interval_seconds,
    is_system = EXCLUDED.is_system,
    is_hidden = EXCLUDED.is_hidden,
    metadata = COALESCE(t_scheduler_job.metadata, '{}'::jsonb) || EXCLUDED.metadata,
    updated_at = now();

UPDATE t_scheduler_job
SET
    description = '22:15 从已沉淀的日频事实生成 V1 兼容报告、V2 双分情绪与周期。V2 基线只读取数据库，按精确交易日窗口聚合、每 20 日写入检查点并在运行记录展示当前阶段；历史市场级北向资金流须先由 backfill_market_north_flow 补齐。',
    timeout_seconds = 1800,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"source":"68-market-emotion-baseline-performance.sql","v2_baseline_progress":true,"v2_baseline_timeout_seconds":1800}'::jsonb,
    updated_at = now()
WHERE job_code = 'calculate_market_daily_sentiment';

INSERT INTO t_scheduler_job_tag (job_code, tag_code)
SELECT job.job_code, tag.tag_code
FROM t_scheduler_job AS job
JOIN t_scheduler_tag AS tag ON tag.tag_code = 'history'
WHERE job.job_code = 'backfill_market_north_flow'
ON CONFLICT (job_code, tag_code) DO NOTHING;

COMMIT;
