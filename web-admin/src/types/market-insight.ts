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
