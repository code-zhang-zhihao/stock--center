-- sync_index_catalog 指数权重查询窗口参数 + t_index_component 冗余约束清理
-- 需要由 t_index_component owner 或 postgres 执行；DROP CONSTRAINT 为幂等清理。

ALTER TABLE t_index_component
    DROP CONSTRAINT IF EXISTS t_index_component_index_code_stock_code_effective_date_sour_key;

UPDATE t_scheduler_job
SET
    description = '低频同步核心指数基础资料与当前成分股主数据，补齐 t_index_basic/t_index_component；Tushare index_weight 默认回看最近 3 个自然月并取最新完整 trade_date，AkShare 仅作 fallback。',
    parameter_schema = jsonb_set(
        parameter_schema,
        '{weight_lookback_months}',
        '{
          "label": "权重回看月数",
          "type": "number",
          "default": 3,
          "required": false,
          "min": 1,
          "max": 24,
          "description": "Tushare index_weight 按最近几个自然月查询，并取最新完整 trade_date 作为当前指数成分。"
        }'::jsonb,
        true
    ),
    default_payload = jsonb_set(
        default_payload,
        '{weight_lookback_months}',
        '3'::jsonb,
        true
    ),
    metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
        'index_weight_lookback_months', 3,
        'index_component_semantics', 'current_master',
        'updated_by_sql', '41-index-weight-lookback-months.sql'
    ),
    updated_at = now()
WHERE job_code = 'sync_index_catalog';
