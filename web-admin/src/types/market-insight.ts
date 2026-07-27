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
