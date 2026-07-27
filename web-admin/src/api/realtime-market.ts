import { requestData } from './client';
import type { RealtimeMarketOverview } from '@/types/realtime-market';

export const realtimeMarketApi = {
  marketOverview: () => requestData<RealtimeMarketOverview>({ method: 'GET', url: '/realtime/market-overview' }),
};
