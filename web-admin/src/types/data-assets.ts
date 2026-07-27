export interface DataAssetMetric {
  label: string;
  value: number | string | null;
  unit?: string | null;
}

export interface DataAssetStatus {
  code: string;
  label: string;
  level: 'success' | 'warning' | 'error' | 'default' | string;
}

export interface DataAssetCoverage {
  scope: string;
  trade_date: string | null;
  expected_count: number;
  actual_count: number;
  exempt_count: number;
  missing_count: number;
  completeness_pct: number | null;
  effective_completeness_pct: number | null;
  reason_breakdown: Record<string, number>;
}

export interface DataAssetItem {
  asset_code: string;
  asset_name: string;
  category: string;
  data_phase: string | null;
  producer_job_codes: string[];
  table_name: string;
  frequency: string;
  row_count: number;
  latest_trade_date: string | null;
  earliest_trade_date: string | null;
  latest_at: string | null;
  latest_count: number | null;
  stale_trade_days: number | null;
  coverage: DataAssetCoverage | null;
  status: DataAssetStatus;
  metrics: DataAssetMetric[];
  warnings: string[];
}

export interface DataAssetGapRow {
  stock_code: string;
  stock_name: string | null;
  exchange: string | null;
  status: string | null;
  reason: string;
  reason_label: string;
}

export interface DataAssetGapReport {
  asset_code: string;
  asset_name: string;
  table_name: string;
  trade_date: string | null;
  expected_count: number;
  actual_count: number;
  exempt_count: number;
  missing_count: number;
  reason_breakdown: Record<string, number>;
  rows: DataAssetGapRow[];
  truncated: boolean;
}

export interface SchedulerRunBrief {
  job_code: string;
  job_name: string | null;
  status: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface DataAssetSummary {
  generated_at: string;
  latest_open_trade_date: string | null;
  totals: Record<string, number>;
  assets: DataAssetItem[];
  scheduler_runs: SchedulerRunBrief[];
  notes: string[];
}

export interface DataAssetDailyHealthCell {
  asset_code: string;
  asset_name: string;
  expected_count: number;
  actual_count: number;
  exempt_count: number;
  missing_count: number;
  effective_completeness_pct: number | null;
  status: DataAssetStatus;
}

export interface DataAssetDailyHealthRow {
  trade_date: string;
  cells: DataAssetDailyHealthCell[];
}

export interface DataAssetDailyHealthReport {
  generated_at: string;
  trade_dates: string[];
  asset_codes: string[];
  rows: DataAssetDailyHealthRow[];
}

export interface DataAssetCacheStatusItem {
  snapshot_key: string;
  status: string | null;
  generated_at: string | null;
  expires_at: string | null;
  refreshed_at: string | null;
  is_stale: boolean;
  error_message: string | null;
}

export interface DataAssetCacheStatusReport {
  generated_at: string;
  items: DataAssetCacheStatusItem[];
}

export interface RealtimeRoundMeta {
  round_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  provider: string;
  expected_count: number;
  received_count: number;
  missing_count: number;
  failed_batch_count: number;
  duration_ms: number | null;
  degraded: boolean;
  error_samples: string[];
}

export interface RealtimeBlockMeta extends RealtimeRoundMeta {
  block: 'market' | 'decision_quote' | 'depth' | 'minute' | string;
  request_count: number;
  coverage_pct: number | null;
  cache_freshness_seconds: number | null;
  rate_limited_count: number;
  network_error_count: number;
  degraded_reason: string | null;
}

export interface RealtimeRateBudget {
  purchased_limit_per_minute: number;
  safety_ratio: number;
  safe_budget_per_minute: number;
  used_requests_in_window: number;
  remaining_requests_in_window: number;
  cooldown_remaining_seconds: number;
  rate_limited_count: number;
}

export interface RealtimeMinuteMeta {
  selected_count: number;
  registered_count: number;
  updated_count: number;
  no_intraday_data_count: number;
  failed_count: number;
  duration_ms: number | null;
  error_samples: string[];
}

export interface RealtimeHealth {
  running: boolean;
  enabled: boolean;
  market_session: boolean;
  cache_backend: string;
  cache_prefix: string;
  quote_cache_count: number;
  quote_stale_count: number;
  minute_cache_count: number;
  minute_registered_count: number;
  minute_guaranteed_count: number;
  reference_loaded_at: string | null;
  last_quote_round: RealtimeRoundMeta;
  last_minute_round: RealtimeMinuteMeta;
  market: RealtimeBlockMeta;
  decision_quote: RealtimeBlockMeta;
  depth: RealtimeBlockMeta;
  minute: RealtimeBlockMeta;
  rate_budgets: Record<string, RealtimeRateBudget>;
  leader_active: boolean;
  depth_cache_count: number;
  decision_target_count: number;
  warm_target_count: number;
  error: string | null;
}

export interface DataAssetRefreshResult {
  refreshed_keys: string[];
  failed_keys: string[];
  summary_rows: number;
  daily_health_rows: number;
  generated_at: string;
}

export interface DataAssetRefreshQueuedResult {
  accepted: boolean;
  snapshot_key: string;
  days: number;
  queued_at: string;
  message: string;
}
