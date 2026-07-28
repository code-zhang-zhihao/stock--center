export type StrategyStatus = 'draft' | 'research' | 'enabled' | 'archived';
export type StrategyEntryMode = 'auction' | 'open' | 'intraday';

export interface StrategyDefinition {
  strategy_code: string;
  strategy_name: string;
  description: string | null;
  status: StrategyStatus;
  strategy_type: string;
  entry_mode: StrategyEntryMode;
  max_holding_trade_days: number;
  rule_config: Record<string, unknown>;
  risk_config: Record<string, unknown>;
  pool_code: string | null;
  pool_name: string | null;
  candidate_summary: {
    total_count?: number;
    latest_signal_trade_date?: string | null;
    awaiting_count?: number;
    not_triggered_count?: number;
  };
  trade_summary: {
    total_count?: number;
    open_count?: number;
    closed_count?: number;
    average_realized_pnl_pct?: number | null;
  };
  created_at: string;
  updated_at: string;
}

export interface StrategyCandidate {
  id: number;
  strategy_code: string;
  strategy_name: string;
  signal_trade_date: string;
  stock_code: string;
  stock_name: string | null;
  candidate_status: 'pending_confirmation' | 'watching' | 'entry_triggered' | 'not_triggered' | 'expired' | 'cancelled' | string;
  score: number | null;
  rank_no: number | null;
  confirmation_deadline: string | null;
  candidate_snapshot: Record<string, unknown>;
  entry_plan: Record<string, unknown>;
  outcome_note: string | null;
  confirmed_at: string | null;
  paper_trade: {
    trade_status: 'open' | 'closed' | 'void' | string;
    entry_at: string;
    entry_price: number;
    quantity: number;
    exit_at: string | null;
    exit_price: number | null;
    realized_pnl_pct: number | null;
    risk_plan: Record<string, unknown>;
  } | null;
}

export interface StrategyDashboard {
  definitions: StrategyDefinition[];
  latest_signal_trade_date: string | null;
  candidate_counts: Record<string, number>;
  paper_trade_counts: Record<string, number>;
  execution_ready: boolean;
  execution_readiness_reason: string;
}
