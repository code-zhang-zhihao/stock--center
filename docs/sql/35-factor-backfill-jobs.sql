-- stock-center 历史因子回填任务
-- Safe to re-run. It only creates/updates scheduler job definitions.

WITH job_defs AS (
    SELECT *
    FROM (
        VALUES
        (
            'backfill_daily_factors',
            '历史个股日频因子回填',
            '按股票池和交易日区间读取 canonical 日线、资金流和专业技术因子，重算 t_stock_factor_daily；不调用外部 Provider、不拉分钟线、不触发策略。',
            '{
              "pool_code":{"label":"股票池编码","type":"string","default":"focus","required":true,"description":"指定需要回填日频因子的股票池；all_a_share 表示沪深 active 动态全市场。"},
              "start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true,"description":"因子回填开始日期，格式 YYYY-MM-DD。只读取已沉淀 canonical 数据，不触发外部 Provider。"},
              "end_date":{"label":"结束日期","type":"string","required":false,"description":"为空时使用交易日历中的最近开市日。"},
              "only_missing":{"label":"只补缺失日期","type":"boolean","default":true,"required":false,"description":"开启后，某交易日目标因子已存在时跳过；部分缺失日期会整体重算该日。"},
              "max_stocks":{"label":"股票数量上限","type":"number","required":false,"min":1,"description":"调试时限制回填股票数量；为空表示整个股票池。"},
              "batch_size":{"label":"计算批次大小","type":"number","default":200,"required":false,"min":20,"max":1000,"description":"每批加载多少只股票计算日频因子。"},
              "calculate_stock_fund":{"label":"计算资金因子","type":"boolean","default":true,"required":false,"description":"从 t_stock_fund_flow_daily 读取资金流，补充资金占比、连续流入、横截面分位等 features。"},
              "include_external_technical":{"label":"合并专业技术因子","type":"boolean","default":true,"required":false,"description":"从 t_stock_technical_factor_daily 读取 stk_factor_pro 摘要并写入 features.tushare_technical。"},
              "fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false,"description":"关闭时，某交易日失败只记录错误并继续后续日期。"}
            }'::jsonb,
            '{
              "pool_code":"focus",
              "start_date":"2024-01-01",
              "end_date":null,
              "only_missing":true,
              "max_stocks":null,
              "batch_size":200,
              "calculate_stock_fund":true,
              "include_external_technical":true,
              "fail_fast":false
            }'::jsonb,
            '{"source":"35-factor-backfill-jobs.sql","manual_first":true,"factor_kind":"daily"}'::jsonb
        ),
        (
            'backfill_sector_factors',
            '历史板块日频因子回填',
            '按交易日区间读取 canonical 板块行情、板块资金流、成分股日线/资金流和涨停事件，重算 t_sector_factor_daily；不调用外部 Provider、不触发策略。',
            '{
              "start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true,"description":"因子回填开始日期，格式 YYYY-MM-DD。只读取已沉淀 canonical 数据，不触发外部 Provider。"},
              "end_date":{"label":"结束日期","type":"string","required":false,"description":"为空时使用交易日历中的最近开市日。"},
              "only_missing":{"label":"只补缺失日期","type":"boolean","default":true,"required":false,"description":"开启后，某交易日板块因子已存在时跳过。"},
              "batch_size":{"label":"计算批次大小","type":"number","default":200,"required":false,"min":20,"max":1000,"description":"预留参数；板块因子当前按交易日整体计算。"},
              "fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false,"description":"关闭时，某交易日失败只记录错误并继续后续日期。"}
            }'::jsonb,
            '{
              "start_date":"2024-01-01",
              "end_date":null,
              "only_missing":true,
              "batch_size":200,
              "fail_fast":false
            }'::jsonb,
            '{"source":"35-factor-backfill-jobs.sql","manual_first":true,"factor_kind":"sector"}'::jsonb
        )
    ) AS t(job_code, job_name, description, parameter_schema, default_payload, metadata)
)
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
SELECT
    job_code,
    job_name,
    'market_data',
    description,
    parameter_schema,
    'cron',
    NULL,
    'Asia/Shanghai',
    default_payload,
    1,
    300,
    21600,
    0,
    300,
    false,
    true,
    false,
    metadata
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
