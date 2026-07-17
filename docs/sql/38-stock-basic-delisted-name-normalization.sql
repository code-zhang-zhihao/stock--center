-- Normalize stock master rows whose display name already indicates delisting.
-- This only fixes t_stock and stock pool membership; historical market facts are kept.

UPDATE t_stock
SET
    status = 'delisted',
    metadata = coalesce(metadata, '{}'::jsonb)
        || jsonb_build_object(
            'status_normalized_reason', 'name_prefix_delisted',
            'status_normalized_at', now(),
            'previous_status_before_name_check', status
        ),
    updated_at = now()
WHERE status = 'active'
  AND stock_name LIKE '退市%';

DELETE FROM t_stock_pool_member m
USING t_stock s
WHERE s.stock_code = m.stock_code
  AND s.status = 'delisted'
  AND s.stock_name LIKE '退市%';

