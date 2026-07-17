-- Adjust daily close ingest metadata after adding index-bar fallback and
-- deprecating daily northbound A-share holding ingestion.
-- Safe to re-run. No facts are deleted.

BEGIN;

UPDATE t_scheduler_job
SET
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || '{
            "sync_north_hold":{
                "label":"同步北向持股",
                "type":"boolean",
                "default":false,
                "required":false,
                "description":"已不建议作为每日任务启用；日度北向 A 股持股披露口径不稳定。"
            },
            "sync_index_bars":{
                "label":"同步核心指数日线",
                "type":"boolean",
                "default":true,
                "required":false,
                "description":"Tushare index_daily 优先；单指数返回 0 时 fallback 到 AkShare，再 fallback 到 MooTDX。"
            }
        }'::jsonb,
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{"sync_north_hold":false,"sync_index_bars":true}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_market_close_ingest';

COMMIT;
