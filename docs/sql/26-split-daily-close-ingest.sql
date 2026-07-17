-- Split daily close ingestion into core, enrichment, and repair jobs.
-- Also remove the deprecated cyq_chips business persistence table.
-- Safe to re-run. This script intentionally drops t_stock_chip_distribution_daily.

BEGIN;

DROP TABLE IF EXISTS t_stock_chip_distribution_daily;

UPDATE t_factor_definition
SET
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"removed_business_persistence":"cyq_chips","removed_by":"26-split-daily-close-ingest.sql"}'::jsonb,
    updated_at = now()
WHERE source_table = 't_stock_chip_distribution_daily';

INSERT INTO t_scheduler_job (
    job_code,
    job_name,
    job_type,
    description,
    parameter_schema,
    trigger_type,
    cron_expr,
    timezone,
    default_payload,
    max_instances,
    misfire_grace_seconds,
    timeout_seconds,
    retry_count,
    retry_interval_seconds,
    is_enabled,
    is_system,
    is_hidden,
    metadata
)
VALUES
(
    'daily_close_core_ingest',
    '每日收盘核心数据沉淀',
    'market_data',
    '收盘后沉淀稳定事实：个股日线、daily_basic、个股资金流、涨跌停/停复牌、核心指数日线、板块日线、分钟线、EOD quote，并计算基础因子。',
    '{
        "trade_date":{"label":"交易日期","type":"string","required":false,"description":"为空时使用当前上海交易日。"},
        "ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},
        "fail_on_enrichment_error":{"label":"非核心块失败即中断","type":"boolean","default":false,"required":false},
        "minute_retention_trade_days":{"label":"分钟数据保留交易日","type":"number","default":10,"required":false,"min":1,"max":60},
        "minute_max_concurrency":{"label":"MooTDX worker 数","type":"number","default":4,"required":false,"min":1,"max":10},
        "minute_batch_size":{"label":"分钟线批次大小","type":"number","default":200,"required":false,"min":20,"max":1000},
        "quote_batch_size":{"label":"收盘快照批次大小","type":"number","default":200,"required":false,"min":20,"max":1000}
    }'::jsonb,
    'cron',
    '30 19 * * 1-5',
    'Asia/Shanghai',
    '{
        "ingest_mode":"append_safe",
        "fail_on_enrichment_error":false,
        "minute_retention_trade_days":10,
        "minute_max_concurrency":4,
        "minute_batch_size":200,
        "quote_batch_size":200
    }'::jsonb,
    1,
    1800,
    21600,
    1,
    600,
    false,
    true,
    false,
    '{"stage":"core","replaces":"daily_market_close_ingest","source":"26-split-daily-close-ingest.sql"}'::jsonb
),
(
    'daily_close_enrichment_ingest',
    '每日收盘增强数据沉淀',
    'market_data',
    '晚间沉淀更新较晚的增强事实：stk_factor_pro、cyq_perf、龙虎榜席位、市场统计、指数每日指标、板块资金流，并重算增强因子。',
    '{
        "trade_date":{"label":"交易日期","type":"string","required":false,"description":"为空时使用当前上海交易日。"},
        "ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},
        "fail_on_enrichment_error":{"label":"增强数据失败即中断","type":"boolean","default":false,"required":false},
        "chip_universe":{"label":"筹码同步范围","type":"string","default":"all_a_share","required":false,"description":"all_a_share 或股票池 pool_code。"},
        "chip_limit_stocks":{"label":"筹码股票上限","type":"number","required":false,"description":"调试时限制 cyq_perf 股票数量；为空表示不限制。"}
    }'::jsonb,
    'cron',
    '30 22 * * 1-5',
    'Asia/Shanghai',
    '{
        "ingest_mode":"append_safe",
        "fail_on_enrichment_error":false,
        "chip_universe":"all_a_share",
        "chip_limit_stocks":null
    }'::jsonb,
    1,
    1800,
    21600,
    1,
    600,
    false,
    true,
    false,
    '{"stage":"enrichment","replaces":"daily_market_close_ingest","source":"26-split-daily-close-ingest.sql"}'::jsonb
),
(
    'daily_close_repair_ingest',
    '每日收盘缺口修复',
    'market_data',
    '次日滚动修复最近交易日的晚到增强数据缺口，并按依赖重算相关因子。',
    '{
        "trade_date":{"label":"指定交易日期","type":"string","required":false,"description":"为空时修复最近 N 个交易日。"},
        "repair_trade_days":{"label":"修复交易日数量","type":"number","default":3,"required":false,"min":1,"max":10},
        "fail_on_enrichment_error":{"label":"增强数据失败即中断","type":"boolean","default":false,"required":false},
        "chip_universe":{"label":"筹码同步范围","type":"string","default":"all_a_share","required":false},
        "chip_limit_stocks":{"label":"筹码股票上限","type":"number","required":false}
    }'::jsonb,
    'cron',
    '30 8 * * 1-5',
    'Asia/Shanghai',
    '{
        "repair_trade_days":3,
        "fail_on_enrichment_error":false,
        "chip_universe":"all_a_share",
        "chip_limit_stocks":null
    }'::jsonb,
    1,
    1800,
    21600,
    0,
    600,
    false,
    true,
    false,
    '{"stage":"repair","replaces":"daily_market_close_ingest","source":"26-split-daily-close-ingest.sql"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    cron_expr = EXCLUDED.cron_expr,
    timezone = EXCLUDED.timezone,
    default_payload = EXCLUDED.default_payload,
    max_instances = EXCLUDED.max_instances,
    misfire_grace_seconds = EXCLUDED.misfire_grace_seconds,
    timeout_seconds = EXCLUDED.timeout_seconds,
    retry_count = EXCLUDED.retry_count,
    retry_interval_seconds = EXCLUDED.retry_interval_seconds,
    is_system = EXCLUDED.is_system,
    is_hidden = EXCLUDED.is_hidden,
    metadata = COALESCE(t_scheduler_job.metadata, '{}'::jsonb) || EXCLUDED.metadata,
    updated_at = now();

UPDATE t_scheduler_job
SET
    is_enabled = false,
    is_hidden = true,
    cron_expr = NULL,
    description = '已废弃：每日收盘沉淀已拆分为 daily_close_core_ingest、daily_close_enrichment_ingest、daily_close_repair_ingest。',
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"deprecated":true,"replaced_by":["daily_close_core_ingest","daily_close_enrichment_ingest","daily_close_repair_ingest"],"source":"26-split-daily-close-ingest.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_market_close_ingest';

COMMIT;
