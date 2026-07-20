-- 收敛历史数据资产任务：个股/板块/指数各保留“日频事实 + 日频因子”两段。
-- Safe to re-run. Existing scheduler run logs are retained because they do not reference job definitions by FK.

BEGIN;

ALTER TABLE t_stock_factor_daily
    ADD COLUMN IF NOT EXISTS ma30 NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS ma60 NUMERIC(18, 6);

CREATE TABLE IF NOT EXISTS t_index_factor_daily (
    id BIGSERIAL PRIMARY KEY,
    index_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL DEFAULT 'system:history_backfill',
    ma5 NUMERIC(18, 6),
    ma10 NUMERIC(18, 6),
    ma20 NUMERIC(18, 6),
    ma30 NUMERIC(18, 6),
    ma60 NUMERIC(18, 6),
    return_1d NUMERIC(18, 6),
    amplitude NUMERIC(18, 6),
    volume_ratio NUMERIC(18, 6),
    amount_ratio NUMERIC(18, 6),
    volatility_20d NUMERIC(18, 6),
    turnover_rate NUMERIC(18, 6),
    pe_ttm NUMERIC(18, 6),
    pb NUMERIC(18, 6),
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_index_factor_daily_business UNIQUE (index_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_t_index_factor_daily_code_date
    ON t_index_factor_daily(index_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_t_index_factor_daily_trade_date
    ON t_index_factor_daily(trade_date DESC, index_code);

COMMENT ON TABLE t_index_factor_daily IS 'Derived 层：由指数日线和指数每日指标计算的指数日频因子。';
COMMENT ON COLUMN t_stock_factor_daily.ma30 IS '30 个有效交易日收盘价均线。';
COMMENT ON COLUMN t_stock_factor_daily.ma60 IS '60 个有效交易日收盘价均线。';

INSERT INTO t_factor_definition (
    factor_code, factor_name, factor_group, frequency, source_table,
    compute_method, is_rebuildable, metadata
)
VALUES
    ('ma30', '30 日均线', 'trend', 'daily', 't_daily_bar', '最近 30 个有效交易日收盘价均值。', TRUE, '{"source":"55-data-asset-history-pipelines.sql"}'::jsonb),
    ('ma60', '60 日均线', 'trend', 'daily', 't_daily_bar', '最近 60 个有效交易日收盘价均值。', TRUE, '{"source":"55-data-asset-history-pipelines.sql"}'::jsonb),
    ('index_daily_factor', '指数日频因子', 'index', 'daily', 't_index_factor_daily', '由 t_index_bar 和 t_index_daily_basic 通过 PostgreSQL 窗口函数批量计算。', TRUE, '{"source":"55-data-asset-history-pipelines.sql"}'::jsonb)
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_group = EXCLUDED.factor_group,
    frequency = EXCLUDED.frequency,
    source_table = EXCLUDED.source_table,
    compute_method = EXCLUDED.compute_method,
    is_rebuildable = EXCLUDED.is_rebuildable,
    metadata = t_factor_definition.metadata || EXCLUDED.metadata,
    updated_at = now();

WITH job_defs AS (
    SELECT * FROM (VALUES
        (
            'backfill_stock_daily_facts',
            '历史个股日频事实回填',
            '依次按股票池逐股区间调用 Tushare daily、daily_basic、moneyflow、stk_factor_pro，并按交易日调用 limit_list_d、suspend_d；不拉历史分钟线。',
            '{"pool_code":{"label":"股票池编码","type":"string","default":"all_a_share","required":true},"start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true},"end_date":{"label":"结束日期","type":"string","required":false},"ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},"only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false},"max_stocks":{"label":"股票数量上限","type":"number","required":false,"min":1},"workers":{"label":"并发 worker 数","type":"number","default":12,"required":false,"min":1,"max":20},"commit_stock_batch_size":{"label":"提交批次股票数","type":"number","default":20,"required":false,"min":1,"max":200},"max_upsert_rows_per_commit":{"label":"单次提交最大行数","type":"number","default":5000,"required":false,"min":100,"max":50000},"include_limit_events":{"label":"回填涨跌停与停牌事件","type":"boolean","default":true,"required":false},"event_workers":{"label":"事件交易日 worker 数","type":"number","default":4,"required":false,"min":1,"max":8},"fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false}}'::jsonb,
            '{"pool_code":"all_a_share","start_date":"2024-01-01","end_date":null,"ingest_mode":"append_safe","only_missing":true,"max_stocks":null,"workers":12,"commit_stock_batch_size":20,"max_upsert_rows_per_commit":5000,"include_limit_events":true,"event_workers":4,"fail_fast":false}'::jsonb
        ),
        (
            'backfill_stock_daily_factors',
            '历史个股日频因子与技术快照回填',
            '在 PostgreSQL 内分窗口计算 t_stock_factor_daily 和日频技术快照；不重算历史分钟因子。',
            '{"pool_code":{"label":"股票池编码","type":"string","default":"all_a_share","required":true},"start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true},"end_date":{"label":"结束日期","type":"string","required":false},"ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},"only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false},"max_stocks":{"label":"股票数量上限","type":"number","required":false,"min":1},"factor_window_trade_days":{"label":"回填窗口交易日数","type":"number","default":20,"required":false,"min":5,"max":60},"sql_stock_chunk_size":{"label":"数据库分片股票数","type":"number","default":200,"required":false,"min":50,"max":500},"calculate_stock_fund":{"label":"计算资金因子","type":"boolean","default":true,"required":false},"include_external_technical":{"label":"合并专业技术因子","type":"boolean","default":true,"required":false},"fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false}}'::jsonb,
            '{"pool_code":"all_a_share","start_date":"2024-01-01","end_date":null,"ingest_mode":"append_safe","only_missing":true,"max_stocks":null,"factor_window_trade_days":20,"sql_stock_chunk_size":200,"calculate_stock_fund":true,"include_external_technical":true,"fail_fast":false}'::jsonb
        ),
        (
            'backfill_sector_daily_facts',
            '历史板块日频事实回填',
            '逐板块完整日期区间回填 Tushare ths_daily，概念/行业资金流按已验证的 20 交易日窗口批量查询。',
            '{"start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true},"end_date":{"label":"结束日期","type":"string","required":false},"ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},"max_sectors":{"label":"板块数量上限","type":"number","required":false,"min":1},"workers":{"label":"板块日 K worker 数","type":"number","default":12,"required":false,"min":1,"max":20},"moneyflow_workers":{"label":"资金流窗口 worker 数","type":"number","default":2,"required":false,"min":1,"max":4},"moneyflow_window_trade_days":{"label":"资金流区间交易日数","type":"number","default":20,"required":false,"min":1,"max":20},"fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false}}'::jsonb,
            '{"start_date":"2024-01-01","end_date":null,"ingest_mode":"append_safe","max_sectors":null,"workers":12,"moneyflow_workers":2,"moneyflow_window_trade_days":20,"fail_fast":false}'::jsonb
        ),
        (
            'backfill_sector_daily_factors',
            '历史板块日频因子回填',
            '按交易日读取板块行情、板块资金流、当前成分、个股日线/资金流与涨停事件，重算 t_sector_factor_daily。',
            '{"start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true},"end_date":{"label":"结束日期","type":"string","required":false},"ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},"only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false},"batch_size":{"label":"计算批次大小","type":"number","default":200,"required":false,"min":20,"max":1000},"calculation_workers":{"label":"计算 worker 数","type":"number","default":2,"required":false,"min":1,"max":4},"fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false}}'::jsonb,
            '{"start_date":"2024-01-01","end_date":null,"ingest_mode":"append_safe","only_missing":true,"batch_size":200,"calculation_workers":2,"fail_fast":false}'::jsonb
        ),
        (
            'backfill_index_daily_facts',
            '历史指数日频事实回填',
            '按 t_index_basic 指数清单逐指数区间调用 Tushare index_daily 与 index_dailybasic。',
            '{"start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true},"end_date":{"label":"结束日期","type":"string","required":false},"ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},"only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false},"max_indexes":{"label":"指数数量上限","type":"number","required":false,"min":1},"workers":{"label":"外部请求 worker 数","type":"number","default":4,"required":false,"min":1,"max":8},"fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false}}'::jsonb,
            '{"start_date":"2024-01-01","end_date":null,"ingest_mode":"append_safe","only_missing":true,"max_indexes":null,"workers":4,"fail_fast":false}'::jsonb
        ),
        (
            'backfill_index_daily_factors',
            '历史指数日频因子回填',
            '在 PostgreSQL 内由 t_index_bar 与 t_index_daily_basic 批量计算 t_index_factor_daily。',
            '{"start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true},"end_date":{"label":"结束日期","type":"string","required":false},"ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},"only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false},"max_indexes":{"label":"指数数量上限","type":"number","required":false,"min":1},"factor_window_trade_days":{"label":"回填窗口交易日数","type":"number","default":20,"required":false,"min":5,"max":60},"sql_stock_chunk_size":{"label":"数据库分片指数数","type":"number","default":200,"required":false,"min":50,"max":500},"fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false}}'::jsonb,
            '{"start_date":"2024-01-01","end_date":null,"ingest_mode":"append_safe","only_missing":true,"max_indexes":null,"factor_window_trade_days":20,"sql_stock_chunk_size":200,"fail_fast":false}'::jsonb
        )
    ) AS t(job_code, job_name, description, parameter_schema, default_payload)
)
INSERT INTO t_scheduler_job (
    job_code, job_name, job_type, description, parameter_schema,
    trigger_type, cron_expr, timezone, default_payload, max_instances,
    misfire_grace_seconds, timeout_seconds, retry_count, retry_interval_seconds,
    is_enabled, is_system, is_hidden, metadata
)
SELECT
    job_code, job_name, 'market_data', description, parameter_schema,
    'cron', NULL, 'Asia/Shanghai', default_payload, 1,
    300, 86400, 0, 300,
    FALSE, TRUE, FALSE,
    jsonb_build_object('source', '55-data-asset-history-pipelines.sql', 'manual_first', TRUE, 'pipeline_version', 3)
FROM job_defs
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    timezone = EXCLUDED.timezone,
    default_payload = EXCLUDED.default_payload,
    timeout_seconds = EXCLUDED.timeout_seconds,
    retry_interval_seconds = EXCLUDED.retry_interval_seconds,
    is_system = EXCLUDED.is_system,
    is_hidden = EXCLUDED.is_hidden,
    metadata = COALESCE(t_scheduler_job.metadata, '{}'::jsonb) || EXCLUDED.metadata,
    updated_at = now();

DELETE FROM t_scheduler_job
WHERE job_code IN (
    'backfill_stock_daily_bars',
    'backfill_stock_daily_basic',
    'backfill_stock_moneyflow',
    'backfill_stock_technical_factor_pro',
    'backfill_daily_factors',
    'backfill_technical_snapshots',
    'backfill_sector_factors'
);

COMMIT;
