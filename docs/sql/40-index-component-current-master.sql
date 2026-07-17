-- stock-center 指数成分收口为当前主数据
-- t_index_component 不再按 effective_date/source 保留多份快照。
-- 业务唯一键固定为 (index_code, stock_code)，同步时移除不再属于当前指数的旧成分。

BEGIN;

WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY index_code, stock_code
            ORDER BY
                CASE
                    WHEN source = 'tushare:index_weight' THEN 1
                    WHEN source = 'akshare:index_stock_cons' THEN 2
                    ELSE 9
                END,
                effective_date DESC NULLS LAST,
                created_at DESC,
                id DESC
        ) AS rn
    FROM t_index_component
)
DELETE FROM t_index_component c
USING ranked r
WHERE c.id = r.id
  AND r.rn > 1;

ALTER TABLE t_index_component
    DROP CONSTRAINT IF EXISTS uq_t_index_component_index_stock_date_source;

ALTER TABLE t_index_component
    DROP CONSTRAINT IF EXISTS uq_t_index_component_index_stock;

ALTER TABLE t_index_component
    ADD CONSTRAINT uq_t_index_component_index_stock UNIQUE (index_code, stock_code);

CREATE INDEX IF NOT EXISTS idx_t_index_component_index_code
    ON t_index_component (index_code);

COMMENT ON TABLE t_index_component IS 'Canonical：指数当前成分股主数据，只保留当前有效关联。';
COMMENT ON COLUMN t_index_component.effective_date IS '成分纳入或权重生效日期；不作为快照维度。';
COMMENT ON COLUMN t_index_component.source IS '当前成分关系的最终数据来源。';
COMMENT ON CONSTRAINT uq_t_index_component_index_stock ON t_index_component IS '指数成分主数据唯一键：同一指数下同一股票只保留当前一条关系。';

COMMIT;
