export interface RealtimeMarketQuote {
  stock_code: string;
  stock_name?: string | null;
  source_symbol?: string | null;
  last_price?: number | null;
  change_pct?: number | null;
  amount_yuan?: number | null;
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
    average_change_pct?: number | null;
    median_change_pct?: number | null;
    total_amount_yuan?: number | null;
    change_distribution?: Record<string, number>;
    limit_events?: { available: boolean; reason?: string | null; limit_up_count?: number | null; limit_down_count?: number | null };
    core_indexes?: Array<{
      index_code: string;
      index_name: string;
      source_symbol: string;
      available: boolean;
      quote: RealtimeMarketQuote | null;
    }>;
  };
}
