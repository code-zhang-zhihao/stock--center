-- Deprecate EOD quote snapshots as daily canonical facts.
-- Safe to re-run. This script does not delete t_quote_snapshot history.

BEGIN;

UPDATE t_scheduler_job
SET
    description = replace(
        COALESCE(description, ''),
        '、EOD quote',
        ''
    ),
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        - 'sync_eod_quote'
        - 'quote_batch_size',
    default_payload = (COALESCE(default_payload, '{}'::jsonb)
        - 'sync_eod_quote'
        - 'quote_batch_size'),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"eod_quote_deprecated": true, "source": "45-deprecate-eod-quote-snapshot.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_core_ingest';

UPDATE t_scheduler_job
SET
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        - 'sync_eod_quote'
        - 'quote_batch_size',
    default_payload = (COALESCE(default_payload, '{}'::jsonb)
        - 'sync_eod_quote'
        - 'quote_batch_size'),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"eod_quote_deprecated": true, "source": "45-deprecate-eod-quote-snapshot.sql"}'::jsonb,
    updated_at = now()
WHERE job_code IN ('daily_close_enrichment_ingest', 'daily_close_repair_ingest');

COMMENT ON TABLE t_quote_snapshot IS 'Deprecated canonical table for persisted quote snapshots. EOD rows are deprecated because daily close OHLCV is uniquely represented by t_daily_bar. Future realtime quote should use Redis/in-memory cache unless a separate short-retention audit table is introduced.';
COMMENT ON COLUMN t_quote_snapshot.snapshot_kind IS 'Snapshot kind. eod is deprecated; realtime persistence is not part of daily canonical completeness.';

COMMIT;
