-- stock-center 历史 Tushare 专业技术因子回填任务
-- Safe to re-run. It only creates/updates scheduler job metadata.

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
    'backfill_stock_technical_factor_pro',
    '历史 Tushare 专业技术因子回填',
    'market_data',
    '按股票池循环调用 Tushare stk_factor_pro 接口，安全补齐 t_stock_technical_factor_daily 历史专业技术因子原始集；按单股完整日期区间请求，数据库写入按行数分批提交。',
    '{
      "pool_code":{"label":"股票池编码","type":"string","default":"focus","required":true,"description":"指定需要回填 Tushare 专业技术因子的股票池；all_a_share 表示沪深 active 动态全市场。"},
      "start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true,"description":"专业技术因子回填开始日期，格式 YYYY-MM-DD。任务按单股完整 start_date/end_date 调用 stk_factor_pro。"},
      "end_date":{"label":"结束日期","type":"string","required":false,"description":"为空时使用交易日历中的最近开市日。"},
      "ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"],"description":"append_safe 幂等补缺，不重复入库；rebuild 会先删除目标股票池和日期范围内的专业技术因子再重建。"},
      "only_missing":{"label":"只补缺失","type":"boolean","default":true,"required":false,"description":"append_safe 模式下为 true 表示只补缺失；rebuild 模式会忽略它。"},
      "max_stocks":{"label":"股票数量上限","type":"number","required":false,"min":1,"description":"调试时限制回填股票数量；为空表示整个股票池。"},
      "workers":{"label":"并发 worker 数","type":"number","default":4,"required":false,"min":1,"max":10,"description":"并发拉取 Tushare stk_factor_pro 的 worker 数；仍受 Tushare Token 池限频控制。"},
      "commit_stock_batch_size":{"label":"提交批次股票数","type":"number","default":20,"required":false,"min":1,"max":200,"description":"每个 worker 累积多少只股票的专业技术因子后提交一次。"},
      "max_upsert_rows_per_commit":{"label":"单次提交最大行数","type":"number","default":5000,"required":false,"min":100,"max":50000,"description":"只限制每次数据库事务最多提交多少行；Tushare stk_factor_pro 仍按单股完整 start_date/end_date 区间请求。"},
      "fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false,"description":"关闭时单只股票失败只记录错误并继续其他股票。"}
    }'::jsonb,
    'cron',
    NULL,
    'Asia/Shanghai',
    '{
      "pool_code":"focus",
      "start_date":"2024-01-01",
      "end_date":null,
      "ingest_mode":"append_safe",
      "only_missing":true,
      "max_stocks":null,
      "workers":4,
      "commit_stock_batch_size":20,
      "max_upsert_rows_per_commit":5000,
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
    '{"source":"49-stock-technical-factor-pro-backfill-job.sql","manual_first":true,"fact_kind":"stock_technical_factor_pro","provider":"tushare","api_name":"stk_factor_pro"}'::jsonb
)
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
