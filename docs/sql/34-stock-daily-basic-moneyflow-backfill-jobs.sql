-- stock-center 历史 daily_basic 与个股资金流回填任务
-- Safe to re-run. It only creates/updates scheduler job definitions.

WITH job_defs AS (
    SELECT *
    FROM (
        VALUES
        (
            'backfill_stock_daily_basic',
            '历史 daily_basic 回填',
            '按股票池循环调用 Tushare daily_basic 接口，安全补齐 t_stock_daily_basic 历史估值、换手率、市值等日频事实；不计算因子、不触发策略。',
            '{
              "pool_code":{"label":"股票池编码","type":"string","default":"focus","required":true,"description":"指定需要回填 daily_basic 的股票池；all_a_share 表示沪深 active 动态全市场。"},
              "start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true,"description":"daily_basic 回填开始日期，格式 YYYY-MM-DD。"},
              "end_date":{"label":"结束日期","type":"string","required":false,"description":"为空时使用交易日历中的最近开市日。"},
              "only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false,"description":"开启后仅写入 t_stock_daily_basic 尚缺失的 stock_code + trade_date。"},
              "max_stocks":{"label":"股票数量上限","type":"number","required":false,"min":1,"description":"调试时限制回填股票数量；为空表示整个股票池。"},
              "workers":{"label":"并发 worker 数","type":"number","default":4,"required":false,"min":1,"max":10,"description":"并发拉取 Tushare daily_basic 的 worker 数；仍受 Tushare Token 池限频控制。"},
              "commit_stock_batch_size":{"label":"提交批次股票数","type":"number","default":20,"required":false,"min":1,"max":200,"description":"每个 worker 累积多少只股票的 daily_basic 后提交一次。"},
              "fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false,"description":"关闭时单只股票失败只记录错误并继续其他股票。"}
            }'::jsonb,
            '{"source":"34-stock-daily-basic-moneyflow-backfill-jobs.sql","manual_first":true,"fact_kind":"daily_basic"}'::jsonb
        ),
        (
            'backfill_stock_moneyflow',
            '历史个股资金流回填',
            '按股票池循环调用 Tushare moneyflow 接口，安全补齐 t_stock_fund_flow_daily 历史个股资金流；金额统一按元入库，不触发策略。',
            '{
              "pool_code":{"label":"股票池编码","type":"string","default":"focus","required":true,"description":"指定需要回填个股资金流的股票池；all_a_share 表示沪深 active 动态全市场。"},
              "start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true,"description":"个股资金流回填开始日期，格式 YYYY-MM-DD。"},
              "end_date":{"label":"结束日期","type":"string","required":false,"description":"为空时使用交易日历中的最近开市日。"},
              "only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false,"description":"开启后仅写入 t_stock_fund_flow_daily 尚缺失的 stock_code + trade_date。"},
              "max_stocks":{"label":"股票数量上限","type":"number","required":false,"min":1,"description":"调试时限制回填股票数量；为空表示整个股票池。"},
              "workers":{"label":"并发 worker 数","type":"number","default":4,"required":false,"min":1,"max":10,"description":"并发拉取 Tushare moneyflow 的 worker 数；仍受 Tushare Token 池限频控制。"},
              "commit_stock_batch_size":{"label":"提交批次股票数","type":"number","default":20,"required":false,"min":1,"max":200,"description":"每个 worker 累积多少只股票的 moneyflow 后提交一次。"},
              "fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false,"description":"关闭时单只股票失败只记录错误并继续其他股票。"}
            }'::jsonb,
            '{"source":"34-stock-daily-basic-moneyflow-backfill-jobs.sql","manual_first":true,"fact_kind":"moneyflow","unit":"yuan"}'::jsonb
        )
    ) AS t(job_code, job_name, description, parameter_schema, metadata)
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
    '{
      "pool_code":"focus",
      "start_date":"2024-01-01",
      "end_date":null,
      "only_missing":true,
      "max_stocks":null,
      "workers":4,
      "commit_stock_batch_size":20,
      "fail_fast":false
    }'::jsonb,
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
