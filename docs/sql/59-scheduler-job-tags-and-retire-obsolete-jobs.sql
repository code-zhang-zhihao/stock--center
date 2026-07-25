-- 调度任务标签与废弃任务清理。
-- Safe to re-run. 删除的是任务定义，不删除历史 t_scheduler_job_run 运行日志。

BEGIN;

CREATE TABLE IF NOT EXISTS t_scheduler_tag (
    id BIGSERIAL PRIMARY KEY,
    tag_code VARCHAR(64) NOT NULL,
    tag_name VARCHAR(80) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_scheduler_tag_code UNIQUE (tag_code),
    CONSTRAINT ck_t_scheduler_tag_sort_order CHECK (sort_order >= 0)
);

CREATE TABLE IF NOT EXISTS t_scheduler_job_tag (
    job_code VARCHAR(120) NOT NULL REFERENCES t_scheduler_job(job_code) ON DELETE CASCADE,
    tag_code VARCHAR(64) NOT NULL REFERENCES t_scheduler_tag(tag_code) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_t_scheduler_job_tag PRIMARY KEY (job_code, tag_code)
);

CREATE INDEX IF NOT EXISTS idx_t_scheduler_job_tag_tag_code_job_code
    ON t_scheduler_job_tag (tag_code, job_code);

COMMENT ON TABLE t_scheduler_tag IS '调度任务展示标签；当前内置历史、每日、主数据、策略，后续可独立扩展。';
COMMENT ON TABLE t_scheduler_job_tag IS '调度任务与标签的多对多关联；删除任务或标签时自动清理关联。';

INSERT INTO t_scheduler_tag (tag_code, tag_name, sort_order, is_enabled, metadata)
VALUES
    ('history', '历史', 10, true, '{"scope":"historical_backfill"}'::jsonb),
    ('daily', '每日', 20, true, '{"scope":"daily_pipeline"}'::jsonb),
    ('master_data', '主数据', 30, true, '{"scope":"master_data_sync"}'::jsonb),
    ('strategy', '策略', 40, true, '{"scope":"strategy_pipeline","reserved":true}'::jsonb)
ON CONFLICT (tag_code) DO UPDATE SET
    tag_name = EXCLUDED.tag_name,
    sort_order = EXCLUDED.sort_order,
    is_enabled = EXCLUDED.is_enabled,
    metadata = COALESCE(t_scheduler_tag.metadata, '{}'::jsonb) || EXCLUDED.metadata,
    updated_at = now();

DELETE FROM t_scheduler_job
WHERE job_code IN (
    'scheduler_noop',
    'daily_market_close_ingest',
    'sync_tushare_a_share_topic'
);

WITH tag_mappings(tag_code, job_code) AS (
    VALUES
        ('history', 'backfill_stock_daily_facts'),
        ('history', 'backfill_stock_daily_factors'),
        ('history', 'backfill_sector_daily_facts'),
        ('history', 'backfill_sector_daily_factors'),
        ('history', 'backfill_index_daily_facts'),
        ('history', 'backfill_index_daily_factors'),
        ('daily', 'daily_close_minute_ingest'),
        ('daily', 'daily_close_core_ingest'),
        ('daily', 'daily_close_enrichment_ingest'),
        ('daily', 'daily_close_repair_ingest'),
        ('daily', 'refresh_data_asset_health'),
        ('master_data', 'sync_trade_calendar'),
        ('master_data', 'sync_stock_basic'),
        ('master_data', 'sync_sector_catalog'),
        ('master_data', 'sync_index_catalog')
)
INSERT INTO t_scheduler_job_tag (job_code, tag_code)
SELECT mapping.job_code, mapping.tag_code
FROM tag_mappings AS mapping
JOIN t_scheduler_job AS job ON job.job_code = mapping.job_code
JOIN t_scheduler_tag AS tag ON tag.tag_code = mapping.tag_code
ON CONFLICT (job_code, tag_code) DO NOTHING;

COMMIT;
