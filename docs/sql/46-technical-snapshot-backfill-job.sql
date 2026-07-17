-- stock-center 技术快照历史回填任务
-- Safe to re-run. It only creates/updates one scheduler job definition.

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
    'backfill_technical_snapshots',
    '历史技术快照回填',
    'market_data',
    '按股票池和交易日区间读取 canonical 日线、分钟线与因子表，重算 t_technical_indicator_snapshot；不调用外部 Provider、不拉取行情、不触发策略。',
    '{
      "pool_code":{"label":"股票池编码","type":"string","default":"all_a_share","required":true,"description":"指定需要回填技术快照的股票池；all_a_share 表示沪深 active 动态全市场。"},
      "start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true,"description":"技术快照回填开始日期，格式 YYYY-MM-DD。只读取已沉淀 canonical 数据，不触发外部 Provider。"},
      "end_date":{"label":"结束日期","type":"string","required":false,"description":"为空时使用交易日历中的最近开市日。"},
      "ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"],"description":"append_safe 幂等补缺，不重复入库；rebuild 会先删除目标范围内的技术快照再重建。"},
      "only_missing":{"label":"只补缺失日期","type":"boolean","default":true,"required":false,"description":"append_safe 模式下，某交易日目标技术快照已完整时跳过；rebuild 模式会忽略它。"},
      "max_stocks":{"label":"股票数量上限","type":"number","required":false,"min":1,"description":"调试时限制回填股票数量；为空表示整个股票池。"},
      "batch_size":{"label":"计算批次大小","type":"number","default":200,"required":false,"min":20,"max":1000,"description":"每批加载多少只股票生成技术快照。"},
      "fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false,"description":"关闭时，某交易日失败只记录错误并继续后续日期。"}
    }'::jsonb,
    'cron',
    NULL,
    'Asia/Shanghai',
    '{
      "pool_code":"all_a_share",
      "start_date":"2024-01-01",
      "end_date":null,
      "ingest_mode":"append_safe",
      "only_missing":true,
      "max_stocks":null,
      "batch_size":200,
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
    '{"source":"46-technical-snapshot-backfill-job.sql","manual_first":true,"factor_kind":"technical_snapshot","ingest_mode_supported":true}'::jsonb
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
