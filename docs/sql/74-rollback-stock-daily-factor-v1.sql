-- Emergency semantic rollback.  No V2 rows are removed.

BEGIN;

UPDATE t_factor_set_version
SET status = 'shadow', updated_at = now()
WHERE factor_set_code = 'stock_daily_v2' AND status = 'active';

UPDATE t_factor_set_version
SET status = 'active', activated_at = now(), updated_at = now()
WHERE factor_set_code = 'stock_daily_v1';

COMMIT;

