-- Add controlled concurrency parameters for daily close enrichment and repair jobs.
-- Safe to re-run. This script only patches parameter_schema/default_payload.

BEGIN;

UPDATE t_scheduler_job
SET
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || '{
            "enrichment_block_concurrency": {
                "label": "增强块并发数",
                "type": "number",
                "default": 4,
                "required": false,
                "min": 1,
                "max": 10,
                "description": "同时运行多少个独立增强数据块；仍受 Tushare Token 池和调度超时限制。"
            },
            "chip_perf_workers": {
                "label": "筹码胜率 worker 数",
                "type": "number",
                "default": 4,
                "required": false,
                "min": 1,
                "max": 10,
                "description": "cyq_perf 按股票逐只调用，该参数控制并发 worker 数。"
            },
            "chip_perf_commit_stock_batch_size": {
                "label": "筹码提交批次股票数",
                "type": "number",
                "default": 100,
                "required": false,
                "min": 1,
                "max": 500,
                "description": "每个 cyq_perf worker 累积多少只股票后提交一次，降低长任务失败影响范围。"
            }
        }'::jsonb,
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{
            "enrichment_block_concurrency": 4,
            "chip_perf_workers": 4,
            "chip_perf_commit_stock_batch_size": 100
        }'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"enrichment_concurrency": true, "source": "30-daily-close-enrichment-concurrency.sql"}'::jsonb,
    updated_at = now()
WHERE job_code IN ('daily_close_enrichment_ingest', 'daily_close_repair_ingest');

COMMIT;
