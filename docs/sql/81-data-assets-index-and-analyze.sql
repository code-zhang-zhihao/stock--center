-- Restore accurate data-center stats and latest-date scans after bulk historical writes.
-- CREATE INDEX CONCURRENTLY cannot run inside a transaction block, so run this file as-is.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_t_stock_adjust_factor_trade_date
    ON t_stock_adjust_factor (trade_date DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_t_provider_ingest_audit_trade_date
    ON t_provider_ingest_audit (trade_date DESC);

-- The database has never been ANALYZEd after the large historical writes: every
-- business table still reports n_live_tup=0.  Refresh planner statistics so the
-- data center shows real row counts and the query planner stops underestimating
-- the sector/leader window scans.
ANALYZE;

SELECT tablename, indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('t_stock_adjust_factor', 't_provider_ingest_audit')
ORDER BY tablename, indexname;
