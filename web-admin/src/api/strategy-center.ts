import { requestData } from './client';
import type { StrategyBacktestRun, StrategyCandidate, StrategyDashboard, StrategyDefinition, StrategyEntryMode, StrategyOptimizationReview, StrategyStatus, StrategyTemplate, StrategyVersion } from '@/types/strategy-center';

export const strategyCenterApi = {
  dashboard: () => requestData<StrategyDashboard>({ method: 'GET', url: '/strategies/dashboard' }),
  templates: () => requestData<StrategyTemplate[]>({ method: 'GET', url: '/strategies/templates' }),
  bootstrapBuiltins: () => requestData<{ created: string[]; skipped: string[]; implementation_version: string }>({ method: 'POST', url: '/strategies/bootstrap-builtins' }),
  create: (payload: {
    strategy_code: string;
    strategy_name: string;
    implementation_code?: string | null;
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
  versions: (strategyCode: string) => requestData<StrategyVersion[]>({ method: 'GET', url: `/strategies/${encodeURIComponent(strategyCode)}/versions` }),
  backtests: (strategyCode: string) => requestData<StrategyBacktestRun[]>({ method: 'GET', url: `/strategies/${encodeURIComponent(strategyCode)}/backtests` }),
  optimizations: (strategyCode: string) => requestData<StrategyOptimizationReview[]>({ method: 'GET', url: `/strategies/${encodeURIComponent(strategyCode)}/optimizations` }),
  createVersion: (strategyCode: string, payload: { implementation_code: string; rule_config?: Record<string, unknown>; risk_config?: Record<string, unknown> }) =>
    requestData<StrategyVersion>({ method: 'POST', url: `/strategies/${encodeURIComponent(strategyCode)}/versions`, data: payload }),
  promoteVersion: (strategyCode: string, versionNo: number) =>
    requestData<StrategyVersion>({ method: 'POST', url: `/strategies/${encodeURIComponent(strategyCode)}/versions/${versionNo}/promote-paper` }),
};
