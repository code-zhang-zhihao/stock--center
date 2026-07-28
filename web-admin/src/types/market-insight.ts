export interface MarketSentimentComponent {
  label: string;
  weight: number;
  raw_value: number | null;
  score: number | null;
  available: boolean;
  formula: string;
}

export interface MarketDailySentiment {
  available: boolean;
  reason?: string | null;
  trade_date: string | null;
  universe_code: string | null;
  calculation_version: string;
  status?: 'pending' | 'ready' | string | null;
  sentiment_score?: number | null;
  stage_code?: string | null;
  stage_label?: string | null;
  components?: Record<string, MarketSentimentComponent>;
  metrics?: Record<string, number | null>;
  coverage?: {
    active_stock_count?: number;
    daily_bar_count?: number;
    daily_bar_coverage_pct?: number | null;
    minimum_daily_bar_coverage_pct?: number;
    limit_event_complete?: boolean;
    completion_capabilities?: string[];
    unavailable_reasons?: string[];
  };
  source_facts?: Record<string, string>;
  calculated_at?: string | null;
}

export interface MarketSectorHeat {
  trade_date: string;
  sector_code: string;
  sector_name: string;
  calculation_version: string;
  status: 'pending' | 'ready' | string;
  heat_score: number | null;
  heat_rank: number | null;
  metrics: Record<string, number | null>;
  components: Record<string, MarketSentimentComponent>;
  leaders: Array<{
    stock_code: string;
    stock_name: string;
    change_pct: number | null;
    close_price: number | null;
    amount_yuan: number | null;
    main_net_inflow: number | null;
    is_limit_up: boolean;
  }>;
  coverage: Record<string, unknown>;
}

export interface MarketLimitUpEvidence {
  trade_date: string;
  stock_code: string;
  stock_name: string | null;
  calculation_version: string;
  status: 'pending' | 'ready' | string;
  board_count: number | null;
  market_snapshot: Record<string, string | number | null>;
  sector_context: Array<{
    sector_code: string;
    sector_name: string;
    heat_score: number | null;
    heat_rank: number | null;
  }>;
  evidence: {
    lhb?: { complete: boolean; records: Array<{ reason: string; net_buy_amount: number | null; turnover_amount: number | null }>; note: string };
    announcements?: { completeness: string; records: Array<{ title: string; category: string | null; published_at: string; url: string | null }>; note: string };
  };
  coverage: Record<string, unknown>;
}

export interface MarketDailyReview {
  available: boolean;
  reason?: string | null;
  trade_date: string | null;
  calculation_version: string;
  sentiment: MarketDailySentiment;
  coverage?: {
    sector_heat_count: number;
    limit_up_evidence_count: number;
    limit_up_evidence_expected_count: number;
    sector_ready: boolean;
    limit_up_evidence_ready: boolean;
    unavailable_reasons: string[];
  };
  sectors: MarketSectorHeat[];
  limit_up_evidence: MarketLimitUpEvidence[];
}

export interface MarketEmotionMetric {
  label?: string;
  raw_value: number | null;
  unit?: string;
  direction?: 'positive' | 'negative' | string;
  percentile_120d?: number | null;
  history_sample_count?: number;
  score?: number | null;
  available: boolean;
  formula?: string;
  source?: string;
  freshness?: string;
  weight?: number;
  effective_weight?: number | null;
  contribution?: number | null;
  included?: boolean;
}

export interface MarketEmotionScorecard {
  label: string;
  score: number | null;
  configured_weight_total: number;
  available_weight_total: number | null;
  items: Record<string, MarketEmotionMetric>;
}

export interface MarketEmotionModel {
  model_code: string;
  model_name: string;
  status: 'draft' | 'calibrating' | 'ready' | 'active' | 'archived' | string;
  percentile_window_days: number;
  minimum_history_days: number;
  baseline_trade_days: number;
  parameter_json: Record<string, unknown>;
  calibration_summary: Record<string, unknown>;
  published_at?: string | null;
  updated_at?: string | null;
}

export interface MarketEmotionDaily {
  available: boolean;
  reason?: string | null;
  trade_date?: string | null;
  model_code?: string;
  status?: 'pending' | 'ready' | 'degraded' | 'insufficient_history' | string;
  short_term_score?: number | null;
  market_risk_on_score?: number | null;
  primary_stage_code?: string | null;
  primary_stage_label?: string | null;
  auxiliary_state_code?: string | null;
  auxiliary_state_label?: string | null;
  metrics?: Record<string, MarketEmotionMetric>;
  scorecards?: { short_term?: MarketEmotionScorecard; risk_on?: MarketEmotionScorecard };
  stage_evidence?: Array<{ rule: string; detail: string }>;
  coverage?: Record<string, unknown>;
  parameter_snapshot?: Record<string, unknown>;
  external_confirmations?: Record<string, unknown>;
  calculated_at?: string | null;
  model?: MarketEmotionModel;
  trend?: Array<{
    trade_date: string;
    short_term_score: number | null;
    market_risk_on_score: number | null;
    primary_stage_code: string | null;
    auxiliary_state_code: string | null;
    status: string;
  }>;
}

export interface MarketEmotionValidationBucket {
  code: 'low' | 'middle' | 'high' | string;
  label: string;
  score_range: string;
  sample_count: number;
  average_market_breadth_pct: number | null;
  average_core_index_cumulative_return_pct: number | null;
  market_breadth_above_50_pct: number | null;
  core_index_positive_pct: number | null;
}

export interface MarketEmotionValidationHorizon {
  sample_count: number;
  average_market_breadth_pct: number | null;
  average_core_index_cumulative_return_pct: number | null;
  market_breadth_rank_correlation: number | null;
  core_index_return_rank_correlation: number | null;
  buckets: MarketEmotionValidationBucket[];
  high_low_difference: {
    breadth_pct_point_difference: number | null;
    core_index_return_pct_point_difference: number | null;
    high_sample_count: number;
    low_sample_count: number;
  };
  relationship: 'positive' | 'inverse' | 'mixed' | 'insufficient_samples' | 'insufficient_outcomes' | string;
}

export interface MarketEmotionValidationPreview {
  available: boolean;
  reason?: string | null;
  model?: MarketEmotionModel;
  history_start_trade_date?: string;
  history_end_trade_date?: string;
  stored_row_count?: number;
  calendar_trade_day_count?: number;
  validation?: {
    method_version: string;
    eligible_score_days: number;
    short_term: { t_plus_1: MarketEmotionValidationHorizon; t_plus_3: MarketEmotionValidationHorizon };
    risk_on: { t_plus_1: MarketEmotionValidationHorizon; t_plus_3: MarketEmotionValidationHorizon };
    outcome_definition: Record<string, string>;
    note: string;
  };
}
