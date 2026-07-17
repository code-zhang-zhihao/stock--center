-- stock-center 核心指数基础与成分同步任务 seed
-- 只写入调度任务定义，不修改表结构；默认禁用，先手动验证。

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
    'sync_index_catalog',
    '同步核心指数基础与成分',
    'market_data',
    '低频同步核心指数基础资料与当前成分股主数据，补齐 t_index_basic/t_index_component；默认 Tushare 主源，AkShare fallback。',
    '{
      "index_codes":{"label":"核心指数代码","type":"array","default":["000001.SH","399001.SZ","399006.SZ","000300.SH","000905.SH","000852.SH","000016.SH"],"required":false,"description":"需要同步基础资料的指数代码，使用 Tushare 官方代码，例如 000300.SH。"},
      "sync_components":{"label":"同步指数成分","type":"boolean","default":true,"required":false,"description":"是否同步指数成分股。上证综指这类宽市场指数默认不拉成分。"},
      "component_index_codes":{"label":"成分指数代码","type":"array","default":["399001.SZ","399006.SZ","000300.SH","000905.SH","000852.SH","000016.SH"],"required":false,"description":"需要同步成分股的指数代码；为空时使用核心指数中的成分型指数。"},
      "weight_lookback_months":{"label":"权重回看月数","type":"number","default":3,"required":false,"min":1,"max":24,"description":"Tushare index_weight 按最近几个自然月查询，并取最新完整 trade_date 作为当前指数成分。"},
      "source":{"label":"主数据源","type":"string","default":"tushare","required":false,"options":["tushare","akshare"],"description":"Tushare 为指数基础和权重主源；AkShare 可作为 fallback。"},
      "fallback_to_akshare":{"label":"启用 AkShare fallback","type":"boolean","default":true,"required":false,"description":"Tushare 无权限、返回空或失败时，是否尝试 AkShare 成分接口。"},
      "provider_timeout_seconds":{"label":"Provider 超时秒数","type":"number","default":120,"required":false,"min":5,"max":600,"description":"单个指数基础/成分请求的超时时间。"}
    }'::jsonb,
    'cron',
    '0 9 * * 0',
    'Asia/Shanghai',
    '{"index_codes":["000001.SH","399001.SZ","399006.SZ","000300.SH","000905.SH","000852.SH","000016.SH"],"sync_components":true,"component_index_codes":["399001.SZ","399006.SZ","000300.SH","000905.SH","000852.SH","000016.SH"],"weight_lookback_months":3,"source":"tushare","fallback_to_akshare":true,"provider_timeout_seconds":120}'::jsonb,
    1,
    1800,
    7200,
    0,
    300,
    false,
    false,
    false,
    '{"source":"stock-center-bootstrap","phase":"market_data_sync","normalized_tables":["t_index_basic","t_index_component"]}'::jsonb
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
    is_hidden = EXCLUDED.is_hidden,
    metadata = EXCLUDED.metadata,
    updated_at = now();
