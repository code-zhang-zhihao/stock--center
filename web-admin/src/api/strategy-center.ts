import { requestData } from './client';
import type { StrategyCandidate, StrategyDashboard, StrategyDefinition, StrategyEntryMode, StrategyStatus } from '@/types/strategy-center';

export const strategyCenterApi = {
  dashboard: () => requestData<StrategyDashboard>({ method: 'GET', url: '/strategies/dashboard' }),
  create: (payload: {
    strategy_code: string;
    strategy_name: string;
    description?: string | null;
    entry_mode: StrategyEntryMode;
    max_holding_trade_days: number;
    rule_config?: Record<string, unknown>;
    risk_config?: Record<string, unknown>;
  }) => requestData<StrategyDefinition>({ method: 'POST', url: '/strategies', data: payload }),
  update: (strategyCode: string, payload: Partial<{
    strategy_name: string;
    description: string | null;
    status: StrategyStatus;
    entry_mode: StrategyEntryMode;
    max_holding_trade_days: number;
    rule_config: Record<string, unknown>;
    risk_config: Record<string, unknown>;
  }>) => requestData<StrategyDefinition>({ method: 'PATCH', url: `/strategies/${encodeURIComponent(strategyCode)}`, data: payload }),
  candidates: (params?: { strategy_code?: string; signal_trade_date?: string; limit?: number }) => requestData<StrategyCandidate[]>({
    method: 'GET',
    url: '/strategies/candidates',
    params,
  }),
};
