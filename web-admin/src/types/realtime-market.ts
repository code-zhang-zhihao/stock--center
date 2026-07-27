export interface RealtimeMarketQuote {
  stock_code: string;
  stock_name?: string | null;
  source_symbol?: string | null;
  last_price?: number | null;
  change_pct?: number | null;
  amount_yuan?: number | null;
  volume_hand?: number | null;
  quote_time?: string | null;
}

export interface RealtimeMarketOverview {
  as_of: string | null;
  round_id: string | null;
  provider?: string;
  items: {
    quote_count?: number;
    expected_quote_count?: number;
    coverage_pct?: number | null;
    up_count?: number;
    down_count?: number;
    flat_count?: number;
    market_breadth?: {
      state?: 'broadly_up' | 'broadly_down' | 'mixed' | string;
      up_ratio_pct?: number;
      down_ratio_pct?: number;
      flat_ratio_pct?: number;
    };
    average_change_pct?: number | null;
    median_change_pct?: number | null;
    total_amount_yuan?: number | null;
    daily_factor_trend?: {
      available: boolean;
      reason?: string | null;
      reference_trade_date?: string | null;
      quote_count?: number;
      factor_quote_count?: number;
      ma5?: RealtimeMarketTrendBucket | null;
      ma20?: RealtimeMarketTrendBucket | null;
      ma60?: RealtimeMarketTrendBucket | null;
      above_all?: RealtimeMarketTrendBucket | null;
    };
    intraday_structure?: {
      open_comparable_count?: number;
      above_open_count?: number;
      below_open_count?: number;
      range_comparable_count?: number;
      at_high_count?: number;
      at_low_count?: number;
    };
    change_distribution?: Record<string, number>;
    limit_events?: { available: boolean; reason?: string | null; limit_up_count?: number | null; limit_down_count?: number | null };
    core_indexes?: Array<{
      index_code: string;
      index_name: string;
      source_symbol: string;
      available: boolean;
      quote: RealtimeMarketQuote | null;
    }>;
    top_gainers?: RealtimeMarketQuote[];
    top_losers?: RealtimeMarketQuote[];
    top_amount?: RealtimeMarketQuote[];
    top_volume?: RealtimeMarketQuote[];
  };
}

export interface RealtimeMarketTrendBucket {
  above_count: number;
  comparable_count: number;
  above_pct: number | null;
}

export interface RealtimeSectorStrength {
  sector_code: string;
  sector_name: string;
  sector_type: 'concept' | 'industry' | string;
  source?: string;
  taxonomy_kind?: string | null;
  raw_universe_ids?: string[];
  as_of: string | null;
  round_id: string | null;
  member_count: number;
  quote_count: number;
  coverage_pct: number | null;
  confidence: 'high' | 'medium' | 'low' | string;
  rank?: number | null;
  previous_rank?: number | null;
  rank_change?: number | null;
  change_pct: number | null;
  median_change_pct: number | null;
  up_count: number;
  down_count: number;
  flat_count: number;
  amount_yuan: number | null;
  limit_events_available: boolean;
  limit_up_count: number | null;
  limit_down_count: number | null;
  heat_score: number | null;
  heat_breakdown?: Record<'change' | 'breadth' | 'limit' | 'liquidity', number>;
  leader?: RealtimeMarketQuote | null;
  laggard?: RealtimeMarketQuote | null;
  leaders?: RealtimeMarketQuote[];
  laggards?: RealtimeMarketQuote[];
}

export interface RealtimeSectorList {
  as_of: string | null;
  round_id: string | null;
  items: RealtimeSectorStrength[];
}

export interface RealtimePoolSummary {
  pool_code: string;
  pool_name: string;
  as_of: string | null;
  round_id: string | null;
  member_count: number;
  quote_count: number;
  coverage_pct: number | null;
  up_count: number;
  down_count: number;
  average_change_pct: number | null;
  median_change_pct: number | null;
  amount_yuan: number | null;
  limit_events_available: boolean;
  limit_up_count: number | null;
  limit_down_count: number | null;
  heat_score: number | null;
  leaders?: RealtimeMarketQuote[];
}

export interface RealtimePoolList {
  as_of: string | null;
  round_id: string | null;
  items: RealtimePoolSummary[];
}

export interface RealtimeMarketTimelinePoint {
  as_of: string | null;
  round_id: string;
  up_count: number | null;
  down_count: number | null;
  flat_count: number | null;
  average_change_pct: number | null;
  median_change_pct: number | null;
  total_amount_yuan: number | null;
  breadth_state: string | null;
  top_concepts: Array<{
    sector_code: string;
    sector_name: string;
    rank: number | null;
    heat_score: number | null;
    change_pct: number | null;
    leader?: RealtimeMarketQuote | null;
  }>;
}

export interface RealtimeMarketTimeline {
  as_of: string | null;
  round_id: string | null;
  trade_date: string | null;
  items: RealtimeMarketTimelinePoint[];
}

export interface RealtimeMarketEvent {
  id: string;
  as_of: string | null;
  round_id: string;
  event_type: 'market_breadth_changed' | 'concept_rank_up' | 'concept_rank_down' | 'concept_leader_changed' | string;
  severity: 'positive' | 'negative' | 'neutral' | string;
  title: string;
  detail: string;
  sector_code?: string;
  sector_name?: string;
  stock_code?: string;
  stock_name?: string;
}

export interface RealtimeMarketEvents {
  as_of: string | null;
  round_id: string | null;
  trade_date: string | null;
  items: RealtimeMarketEvent[];
}

export interface RealtimeRuntimeStatus {
  running: boolean;
  enabled: boolean;
  market_session: boolean;
  leader_active: boolean;
  cache_backend: string;
  market?: {
    cache_freshness_seconds?: number | null;
    coverage_pct?: number | null;
    degraded?: boolean;
    degraded_reason?: string | null;
  };
}
