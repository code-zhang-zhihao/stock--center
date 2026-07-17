-- 19-daily-close-ingest-batching.sql
-- Upgrade daily_market_close_ingest scheduler parameters for batched MooTDX ingestion.
-- Safe to run repeatedly. It only updates scheduler metadata; market data tables are untouched.

BEGIN;

UPDATE t_scheduler_job
SET
    parameter_schema = '{
      "trade_date":{"label":"交易日期","type":"string","required":false,"format":"date","description":"为空时使用当前上海交易日。"},
      "sync_daily":{"label":"同步日线","type":"boolean","default":true,"required":false,"description":"通过 Tushare 批量同步全市场日线。"},
      "sync_daily_basic":{"label":"同步日频基础指标","type":"boolean","default":true,"required":false,"description":"通过 Tushare 批量同步换手、估值和市值等日频基础指标。"},
      "sync_minute":{"label":"同步分钟线","type":"boolean","default":true,"required":false,"description":"通过 MooTDX 同步当日全市场 1 分钟线。"},
      "sync_eod_quote":{"label":"同步收盘快照","type":"boolean","default":true,"required":false,"description":"保存全市场轻量 EOD quote，不保存完整五档。"},
      "calculate_daily_factors":{"label":"计算日频因子","type":"boolean","default":true,"required":false,"description":"从 Canonical 日线计算 MA、收益、振幅、量额比和波动率。"},
      "calculate_minute_factors":{"label":"计算分钟因子","type":"boolean","default":true,"required":false,"description":"从 Canonical 分钟线计算 VWAP、收益、放量比和盘中强度。"},
      "calculate_technical_snapshot":{"label":"计算技术快照","type":"boolean","default":true,"required":false,"description":"基于 EOD quote 和已计算因子写入收盘技术快照。"},
      "minute_retention_trade_days":{"label":"分钟数据保留交易日","type":"number","default":10,"required":false,"min":1,"max":60,"description":"分钟线和分钟因子仅保留最近 N 个开市日分区。"},
      "minute_max_concurrency":{"label":"MooTDX worker 数","type":"number","default":4,"required":false,"min":1,"max":10,"description":"每个 worker 使用独立 MooTDX 连接串行拉取，避免全市场同步时共享 socket。"},
      "minute_batch_size":{"label":"分钟线批次大小","type":"number","default":200,"required":false,"min":20,"max":1000,"description":"分钟线按批次拉取并提交，降低内存峰值和单次失败影响范围。"},
      "quote_batch_size":{"label":"收盘快照批次大小","type":"number","default":200,"required":false,"min":20,"max":1000,"description":"EOD quote 按批量接口获取；批量失败时降级逐只补取。"},
      "ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"],"description":"append_safe 跳过已有完整数据；rebuild 重算指定交易日。"}
    }'::jsonb,
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{"minute_batch_size":200,"quote_batch_size":200}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_market_close_ingest';

COMMIT;
