-- Optimize daily close ingestion into minute, core, enrichment, and gap-repair stages.
-- Safe to re-run. No market fact rows are deleted.

BEGIN;

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
VALUES (
    'daily_close_minute_ingest',
    '每日收盘分钟数据沉淀',
    'market_data',
    '15:30 通过 MooTDX 流水线沉淀当日全市场分钟线，并按股票分片使用 PostgreSQL 集合计算分钟因子；分钟线和分钟因子保留最近 30 个交易日。',
    '{
        "trade_date":{"label":"交易日期","type":"string","required":false,"description":"为空时使用当前上海交易日；分钟任务不补历史日期。"},
        "ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},
        "fail_on_enrichment_error":{"label":"失败即中断","type":"boolean","default":false,"required":false},
        "minute_retention_trade_days":{"label":"分钟数据保留交易日","type":"number","default":30,"required":false,"min":1,"max":60},
        "minute_max_concurrency":{"label":"MooTDX worker 数","type":"number","default":10,"required":false,"min":1,"max":10},
        "minute_batch_size":{"label":"分钟线提交批次股票数","type":"number","default":200,"required":false,"min":20,"max":1000},
        "minute_factor_stock_batch_size":{"label":"分钟因子 SQL 分片股票数","type":"number","default":200,"required":false,"min":50,"max":500,"description":"200 只股票约对应 4.8 万行分钟因子，每片独立提交。"}
    }'::jsonb,
    'cron',
    '30 15 * * 1-5',
    'Asia/Shanghai',
    '{
        "sync_minute":true,
        "calculate_minute_factors":true,
        "minute_retention_trade_days":30,
        "minute_max_concurrency":10,
        "minute_batch_size":200,
        "minute_factor_stock_batch_size":200,
        "ingest_mode":"append_safe"
    }'::jsonb,
    1,
    1800,
    7200,
    1,
    300,
    true,
    true,
    false,
    '{"stage":"minute","pipeline_version":4,"provider":"mootdx","factor_mode":"postgres_set_based_chunked","source":"58-daily-close-four-stage-pipeline.sql"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    trigger_type = EXCLUDED.trigger_type,
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
    description = '18:00 并行沉淀个股日线、daily_basic、资金流、涨跌停/停复牌、核心指数和板块日线；使用 PostgreSQL 集合计算日频基础因子和技术快照，不再重复获取分钟线。',
    parameter_schema = '{
        "trade_date":{"label":"交易日期","type":"string","required":false,"description":"为空时使用当前上海交易日。"},
        "ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},
        "fail_on_enrichment_error":{"label":"非核心块失败即中断","type":"boolean","default":false,"required":false}
    }'::jsonb,
    cron_expr = '0 18 * * 1-5',
    default_payload = '{
        "sync_daily":true,
        "sync_daily_basic":true,
        "sync_stock_technical_factor_pro":false,
        "sync_stock_moneyflow":true,
        "sync_stock_limit_status":true,
        "sync_lhb":false,
        "sync_index_bars":true,
        "sync_index_daily_basic":false,
        "sync_north_hold":false,
        "sync_market_stats":false,
        "sync_sector_bars":true,
        "sync_sector_moneyflow":false,
        "sync_minute":false,
        "calculate_daily_factors":true,
        "calculate_minute_factors":false,
        "calculate_technical_snapshot":true,
        "calculate_stock_fund_factors":true,
        "calculate_external_technical_factors":false,
        "merge_external_technical_factors":false,
        "calculate_sector_factors":false,
        "fail_on_enrichment_error":false,
        "ingest_mode":"append_safe"
    }'::jsonb,
    timeout_seconds = 7200,
    retry_count = 1,
    retry_interval_seconds = 300,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"stage":"core","pipeline_version":4,"minute_stage_removed":true,"sector_bar_batch_size":500,"factor_mode":"postgres_set_based","source":"58-daily-close-four-stage-pipeline.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_core_ingest';

UPDATE t_scheduler_job
SET
    description = '21:30 并行沉淀专业技术因子、龙虎榜、指数每日指标、市场统计和板块资金流；专业技术因子只定向合并到已有日频因子，daily_info 未发布时记为 deferred。',
    parameter_schema = '{
        "trade_date":{"label":"交易日期","type":"string","required":false,"description":"为空时使用当前上海交易日。"},
        "ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},
        "fail_on_enrichment_error":{"label":"增强数据失败即中断","type":"boolean","default":false,"required":false},
        "enrichment_block_concurrency":{"label":"增强块并发数","type":"number","default":4,"required":false,"min":1,"max":10}
    }'::jsonb,
    cron_expr = '30 21 * * 1-5',
    default_payload = '{
        "sync_daily":false,
        "sync_daily_basic":false,
        "sync_stock_technical_factor_pro":true,
        "sync_stock_moneyflow":false,
        "sync_stock_limit_status":false,
        "sync_lhb":true,
        "sync_index_bars":false,
        "sync_index_daily_basic":true,
        "sync_north_hold":false,
        "sync_market_stats":true,
        "sync_sector_bars":false,
        "sync_sector_moneyflow":true,
        "sync_minute":false,
        "calculate_daily_factors":false,
        "calculate_minute_factors":false,
        "calculate_technical_snapshot":false,
        "calculate_stock_fund_factors":false,
        "calculate_external_technical_factors":true,
        "merge_external_technical_factors":true,
        "calculate_sector_factors":true,
        "fail_on_enrichment_error":false,
        "enrichment_block_concurrency":4,
        "ingest_mode":"append_safe"
    }'::jsonb,
    timeout_seconds = 3600,
    retry_count = 1,
    retry_interval_seconds = 300,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"stage":"enrichment","pipeline_version":4,"technical_factor_mode":"targeted_merge","late_optional_blocks":["market_stats"],"source":"58-daily-close-four-stage-pipeline.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_enrichment_ingest';

UPDATE t_scheduler_job
SET
    description = '次日 08:00 检查最近 3 个已有日线交易日的核心与增强数据覆盖，只请求缺失数据块并重算受影响因子；不补历史分钟数据。',
    parameter_schema = '{
        "trade_date":{"label":"指定交易日期","type":"string","required":false,"description":"为空时检查最近 N 个已有日线交易日。"},
        "repair_trade_days":{"label":"修复交易日数量","type":"number","default":3,"required":false,"min":1,"max":10},
        "enrichment_block_concurrency":{"label":"修复块并发数","type":"number","default":4,"required":false,"min":1,"max":10},
        "fail_on_enrichment_error":{"label":"数据块失败即中断","type":"boolean","default":false,"required":false}
    }'::jsonb,
    cron_expr = '0 8 * * 1-5',
    default_payload = '{"repair_trade_days":3,"enrichment_block_concurrency":4,"fail_on_enrichment_error":false}'::jsonb,
    timeout_seconds = 3600,
    retry_count = 0,
    retry_interval_seconds = 300,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"stage":"repair","pipeline_version":4,"repair_mode":"gap_driven","minute_repair":false,"source":"58-daily-close-four-stage-pipeline.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_repair_ingest';

UPDATE t_scheduler_job
SET
    description = '已废弃：每日收盘沉淀已拆分为分钟、核心、增强、缺口修复四级流水线。',
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"deprecated":true,"replaced_by":["daily_close_minute_ingest","daily_close_core_ingest","daily_close_enrichment_ingest","daily_close_repair_ingest"],"source":"58-daily-close-four-stage-pipeline.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_market_close_ingest';

COMMENT ON TABLE t_stock_factor_minute IS
    'Derived 层：按交易日分区持久化的股票分钟因子；每日分钟任务按股票分片使用 PostgreSQL 集合计算，页面直接查询本表。';

COMMIT;
