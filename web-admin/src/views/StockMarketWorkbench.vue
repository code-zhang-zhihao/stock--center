<template>
  <main class="workspace market-page">
    <header class="market-header">
      <div class="stock-search">
        <n-input v-model:value="searchKeyword" clearable placeholder="搜索股票代码 / 名称" @keyup.enter="searchStocks">
          <template #prefix><Search :size="16" /></template>
        </n-input>
        <n-button secondary :loading="searchLoading" @click="searchStocks">搜索</n-button>
        <div v-if="searchItems.length" class="search-results">
          <button v-for="item in searchItems" :key="item.stock_code" type="button" @click="openStock(item.stock_code)">
            <span>{{ item.stock_name }}</span>
            <span class="mono">{{ item.stock_code }}</span>
            <n-tag size="small" :bordered="false" :type="item.status === 'active' ? 'success' : 'warning'">{{ item.status }}</n-tag>
          </button>
        </div>
      </div>

      <div class="header-actions">
        <n-switch v-model:value="autoRefresh" :disabled="overview?.stock.status !== 'active' || activeChart !== 'realtime' || !realtime?.meta.market_session">
          <template #checked>自动刷新</template>
          <template #unchecked>手动刷新</template>
        </n-switch>
        <n-button secondary :loading="loading" @click="loadAll">
          <template #icon><RefreshCw :size="16" /></template>
          刷新
        </n-button>
      </div>
    </header>

    <section class="stock-title-band">
      <div>
        <h1>{{ overview?.stock.stock_name || '个股行情' }}</h1>
        <p>
          <span class="mono">{{ currentStockCode || '-' }}</span>
          <n-tag v-if="overview" size="small" :bordered="false">{{ overview.stock.exchange || '-' }}</n-tag>
          <n-tag v-if="overview" size="small" :bordered="false" :type="overview.stock.status === 'active' ? 'success' : 'warning'">
            {{ statusText(overview.stock.status) }}
          </n-tag>
          <span v-if="realtime?.meta.resolved_source" class="muted">实时源：{{ realtime.meta.resolved_source }}</span>
        </p>
      </div>
      <div class="quote-strip">
        <div>
          <span>{{ latestQuote ? '最新价' : '最新收盘' }}</span>
          <strong>{{ formatNumber(latestPrice) }}</strong>
        </div>
        <div>
          <span>涨跌幅</span>
          <strong :class="numberClass(latestChangePct)">{{ formatPercent(latestChangePct) }}</strong>
        </div>
        <div>
          <span>成交额</span>
          <strong>{{ formatMoney(latestAmount) }}</strong>
        </div>
        <div>
          <span>{{ latestQuote ? '更新时间' : '交易日' }}</span>
          <strong class="time-text">{{ latestQuoteTime }}</strong>
        </div>
      </div>
    </section>

    <n-spin :show="loading">
      <div class="market-grid">
        <section class="panel chart-panel">
          <div class="chart-toolbar">
            <n-tabs v-model:value="activeChart" type="segment" size="small">
              <n-tab name="realtime">实时分时</n-tab>
              <n-tab name="minute">历史分钟</n-tab>
              <n-tab name="daily">日 K</n-tab>
            </n-tabs>
            <div v-if="activeChart === 'minute'" class="date-control">
              <n-date-picker v-model:formatted-value="minuteTradeDate" value-format="yyyy-MM-dd" type="date" clearable size="small" @update:formatted-value="loadMinuteBars" />
            </div>
          </div>
          <div class="chart-context" :class="{ warning: activeChart === 'realtime' && !realtime?.meta.market_session }">
            {{ chartContext }}
          </div>
          <MarketChart
            :option="activeChartOption"
            :loading="chartLoading"
            :empty="activeChartEmpty"
            :empty-text="chartEmptyText"
            height="420px"
          />
          <div v-if="activeChart === 'realtime' && realtime?.meta.errors.length" class="warning-line">
            {{ realtime.meta.errors.slice(0, 2).join('；') }}
          </div>
        </section>

        <aside class="side-panel">
          <section class="panel">
            <div class="panel-title">
              <h2>基础资料</h2>
              <span>{{ overview?.stock.industry || '-' }}</span>
            </div>
            <dl class="info-grid">
              <dt>市场</dt><dd>{{ overview?.stock.market || '-' }}</dd>
              <dt>交易所</dt><dd>{{ overview?.stock.exchange || '-' }}</dd>
              <dt>地区</dt><dd>{{ overview?.stock.area || '-' }}</dd>
              <dt>上市日</dt><dd>{{ overview?.stock.list_date || '-' }}</dd>
              <dt>PE TTM</dt><dd>{{ formatNumber(overview?.daily_basic?.pe_ttm ?? null) }}</dd>
              <dt>PB</dt><dd>{{ formatNumber(overview?.daily_basic?.pb ?? null) }}</dd>
              <dt>换手率</dt><dd>{{ formatPercent(overview?.daily_basic?.turnover_rate ?? null) }}</dd>
              <dt>总市值</dt><dd>{{ formatMoneyFromWan(overview?.daily_basic?.total_mv ?? null) }}</dd>
            </dl>
          </section>

          <section class="panel">
            <div class="panel-title">
              <h2>技术快照</h2>
              <span>{{ overview?.technical_snapshot?.snapshot_time ? formatQuoteTime(overview.technical_snapshot.snapshot_time) : '-' }}</span>
            </div>
            <div class="snapshot-list">
              <div><span>盘中强度</span><strong>{{ formatNumber(latestSnapshot?.intraday_strength ?? null) }}</strong></div>
              <div><span>量能评分</span><strong>{{ formatNumber(latestSnapshot?.volume_score ?? null) }}</strong></div>
              <div><span>趋势评分</span><strong>{{ formatNumber(latestSnapshot?.trend_score ?? null) }}</strong></div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-title">
              <h2>所属板块</h2>
              <span>{{ sectorTags.length }} 个</span>
            </div>
            <div class="sector-tags">
              <router-link v-for="sector in sectorTags.slice(0, 24)" :key="sector.sector_code" :to="`/sectors/${encodeURIComponent(sector.sector_code)}`">
                {{ sector.sector_name }}
              </router-link>
            </div>
          </section>
        </aside>
      </div>

      <section class="analysis-grid">
        <section class="panel">
          <div class="panel-title">
            <div>
              <h2>主力资金</h2>
              <span>按交易日统计，金额单位为元</span>
            </div>
            <div class="fund-window-tabs">
              <n-button v-for="days in fundWindowOptions" :key="days" size="small" :type="fundWindowDays === days ? 'primary' : 'default'" @click="fundWindowDays = days">
                近 {{ days }} 日
              </n-button>
            </div>
          </div>
          <div class="fund-summary">
            <div>
              <span>区间主力净额</span>
              <strong :class="numberClass(fundWindowNetInflow)">{{ formatMoney(fundWindowNetInflow) }}</strong>
            </div>
            <div>
              <span>资金结论</span>
              <strong :class="numberClass(fundWindowNetInflow)">{{ fundWindowDirection }}</strong>
            </div>
            <div>
              <span>有效交易日</span>
              <strong>{{ fundWindowItems.length }} 日</strong>
            </div>
          </div>
          <MarketChart :option="fundFlowOption" :empty="!fundFlow?.items.length" empty-text="暂无资金流数据" height="300px" />
        </section>

        <section class="panel factor-panel">
          <div class="panel-title">
            <div>
              <h2>趋势与技术指标</h2>
              <span>系统自算基础因子 + Tushare 专业指标</span>
            </div>
            <span>{{ latestDailyFactor?.trade_date || '-' }}</span>
          </div>
          <div class="factor-section-label">价格趋势</div>
          <div class="factor-grid">
            <Metric label="5日均线" hint="近5日收盘均价" :value="formatNumber(latestDailyFactor?.ma5 ?? null)" />
            <Metric label="10日均线" hint="近10日收盘均价" :value="formatNumber(latestDailyFactor?.ma10 ?? null)" />
            <Metric label="20日均线" hint="近20日收盘均价" :value="formatNumber(latestDailyFactor?.ma20 ?? null)" />
            <Metric label="30日均线" hint="近30日收盘均价" :value="formatNumber(latestDailyFactor?.ma30 ?? null)" />
            <Metric label="60日均线" hint="近60日收盘均价" :value="formatNumber(latestDailyFactor?.ma60 ?? null)" />
            <Metric label="当日涨跌" hint="相对昨收" :value="formatPercent(latestDailyFactor?.return_1d ?? null)" :tone="numberTone(latestDailyFactor?.return_1d ?? null)" />
            <Metric label="日内振幅" hint="最高与最低价差" :value="formatPercent(latestDailyFactor?.amplitude ?? null)" />
            <Metric label="20日波动率" hint="近20日收益波动" :value="formatPercent(latestDailyFactor?.volatility_20d ?? null)" />
            <Metric label="收盘位置" hint="当日区间内位置" :value="formatRatioPercent(latestDailyFactor?.close_position ?? null)" />
          </div>
          <div class="factor-section-label">专业技术指标</div>
          <div class="factor-grid">
            <Metric label="MACD 柱" hint="动量柱值" :value="formatNumber(technicalNumber('macd'))" :tone="numberTone(technicalNumber('macd'))" />
            <Metric label="RSI(6)" hint="短周期强弱" :value="formatNumber(technicalNumber('rsi6'))" />
            <Metric label="KDJ" hint="随机指标 J 值" :value="formatNumber(technicalNumber('kdj'))" />
            <Metric label="布林上轨" hint="20日波动通道" :value="formatNumber(technicalNumber('bollUpper'))" />
            <Metric label="ATR" hint="平均真实波幅" :value="formatNumber(technicalNumber('atr'))" />
          </div>
          <p v-if="factors?.missing.technical_factor" class="muted-hint">专业技术因子待晚间增强/修复任务补齐。</p>
        </section>

        <section class="panel factor-panel">
          <div class="panel-title">
            <div>
              <h2>资金因子</h2>
              <span>资金因子为标准化日频数据</span>
            </div>
            <span>{{ latestDailyFactor?.trade_date || '-' }}</span>
          </div>
          <div class="factor-grid">
            <Metric label="主力净额占比" hint="主力净额 / 成交额" :value="formatRatioPercent(featureNumber('main_net_ratio'))" :tone="numberTone(featureNumber('main_net_ratio'))" />
            <Metric label="超大单净额占比" hint="超大单净额 / 成交额" :value="formatRatioPercent(featureNumber('super_large_net_ratio'))" :tone="numberTone(featureNumber('super_large_net_ratio'))" />
            <Metric label="连续主力流入" hint="连续净流入交易日" :value="formatDays(featureNumber('continuous_main_inflow_days'))" />
            <Metric label="3日主力净额" hint="近3个交易日累计" :value="formatMoney(featureNumber('main_net_inflow_3d'))" :tone="numberTone(featureNumber('main_net_inflow_3d'))" />
            <Metric label="5日主力净额" hint="近5个交易日累计" :value="formatMoney(featureNumber('main_net_inflow_5d'))" :tone="numberTone(featureNumber('main_net_inflow_5d'))" />
            <Metric label="10日主力净额" hint="近10个交易日累计" :value="formatMoney(featureNumber('main_net_inflow_10d'))" :tone="numberTone(featureNumber('main_net_inflow_10d'))" />
            <Metric label="资金强度分位" hint="当日全市场横截面" :value="formatRatioPercent(featureNumber('fund_strength_percentile'))" />
          </div>
        </section>

        <section class="panel">
          <div class="panel-title">
            <h2>分钟因子</h2>
            <span>{{ factors?.minute_factor_trade_date || '-' }} · {{ latestMinuteFactor?.bar_time ? formatBarTime(latestMinuteFactor.bar_time) : '-' }}</span>
          </div>
          <MarketChart :option="minuteFactorOption" :empty="!factors?.minute_factors.length" empty-text="暂无分钟因子" height="300px" />
        </section>
      </section>

      <section class="panel events-panel">
        <div class="panel-title">
          <h2>事件与公告</h2>
          <span>龙虎榜、涨跌停、公告</span>
        </div>
        <div class="events-grid">
          <n-data-table :columns="limitColumns" :data="events?.limit_events || []" :pagination="false" size="small" striped />
          <n-data-table :columns="lhbColumns" :data="events?.lhb_events || []" :pagination="false" size="small" striped />
          <n-data-table :columns="announcementColumns" :data="events?.announcements || []" :pagination="false" size="small" striped />
        </div>
      </section>
    </n-spin>
  </main>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter, RouterLink } from 'vue-router';
import type { EChartsOption } from 'echarts';
import {
  NButton,
  NDataTable,
  NDatePicker,
  NInput,
  NSwitch,
  NSpin,
  NTab,
  NTabs,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui';
import { RefreshCw, Search } from 'lucide-vue-next';
import MarketChart from '@/components/MarketChart.vue';
import { marketDataApi } from '@/api/market-data';
import type {
  StockAnalysisEvents,
  StockAnalysisFactors,
  StockAnalysisMinuteSeries,
  StockAnalysisOverview,
  StockAnalysisRealtime,
  StockAnalysisSeries,
  StockDailyChartBar,
  StockDailyFactor,
  StockFundFlowSeries,
  StockLhbEvent,
  StockLimitEvent,
  StockMinuteBar,
  StockMinuteFactor,
  StockSearchItem,
  StockSectorTag,
  StockAnnouncement,
} from '@/types/market-data';

const Metric = defineComponent({
  props: {
    label: { type: String, required: true },
    hint: { type: String, default: '' },
    value: { type: String, required: true },
    tone: { type: String, default: '' },
  },
  setup(props) {
    return () => h('div', { class: 'metric' }, [
      h('div', { class: 'metric-copy' }, [
        h('span', { class: 'metric-label' }, props.label),
        props.hint ? h('span', { class: 'metric-hint' }, props.hint) : null,
      ]),
      h('strong', { class: props.tone }, props.value),
    ]);
  },
});

const route = useRoute();
const router = useRouter();
const message = useMessage();

const currentStockCode = ref(String(route.query.stock_code || '600519'));
const searchKeyword = ref('');
const searchItems = ref<StockSearchItem[]>([]);
const loading = ref(false);
const chartLoading = ref(false);
const searchLoading = ref(false);
const autoRefresh = ref(false);
const activeChart = ref<'realtime' | 'minute' | 'daily'>('realtime');
const minuteTradeDate = ref<string | null>(null);
const fundWindowDays = ref<3 | 5 | 10 | 20 | 30>(10);
const fundWindowOptions = [3, 5, 10, 20, 30] as const;

const overview = ref<StockAnalysisOverview | null>(null);
const realtime = ref<StockAnalysisRealtime | null>(null);
const dailyBars = ref<StockAnalysisSeries<StockDailyChartBar> | null>(null);
const minuteBars = ref<StockAnalysisMinuteSeries | null>(null);
const factors = ref<StockAnalysisFactors | null>(null);
const fundFlow = ref<StockFundFlowSeries | null>(null);
const events = ref<StockAnalysisEvents | null>(null);

let refreshTimer: number | null = null;
let realtimeEventSource: EventSource | null = null;

const latestQuote = computed(() => realtime.value?.quote || null);
const latestSnapshot = computed(() => factors.value?.latest.technical_snapshot || overview.value?.technical_snapshot || null);
const latestDailyFactor = computed<StockDailyFactor | null>(() => factors.value?.latest.daily_factor || null);
const latestMinuteFactor = computed<StockMinuteFactor | null>(() => factors.value?.minute_factors.at(-1) || null);
const latestPrice = computed(() => latestQuote.value?.last_price ?? overview.value?.latest_daily_bar?.close_price ?? null);
const latestChangePct = computed(() => latestQuote.value?.change_pct ?? overview.value?.latest_daily_bar?.change_pct ?? null);
const latestAmount = computed(() => latestQuote.value?.amount_yuan ?? overview.value?.latest_daily_bar?.amount_yuan ?? null);
const latestQuoteTime = computed(() => latestQuote.value ? formatQuoteTime(latestQuote.value.quote_time) : (overview.value?.latest_daily_bar?.trade_date || '-'));
const sectorTags = computed<StockSectorTag[]>(() => overview.value?.sectors.items || []);
const fundWindowItems = computed(() => (fundFlow.value?.items || []).slice(-fundWindowDays.value));
const fundWindowNetInflow = computed(() => fundWindowItems.value.reduce((total, item) => total + Number(item.main_net_inflow || 0), 0));
const fundWindowDirection = computed(() => {
  if (fundWindowNetInflow.value > 0) return `近 ${fundWindowItems.value.length} 日净流入`;
  if (fundWindowNetInflow.value < 0) return `近 ${fundWindowItems.value.length} 日净流出`;
  return '资金持平';
});
const chartContext = computed(() => {
  if (activeChart.value === 'daily') {
    return `数据库日 K · ${dailyBars.value?.items.length || 0} 个交易日`;
  }
  if (activeChart.value === 'minute') {
    return `数据库分钟线 · ${minuteBars.value?.trade_date || '-'} · ${minuteBars.value?.items.length || 0} 根`;
  }
  const realtimeData = realtime.value;
  if (!realtimeData) return '正在加载实时行情';
  if (!realtimeData.meta.market_session) return '非交易时段 · 展示最后一次缓存，不作为当前实时行情';
  if (realtimeData.meta.cache_status === 'on_demand') return `盘中按需直连 MooTDX · ${realtimeData.quote ? formatQuoteTime(realtimeData.quote.quote_time) : '分时数据已刷新'}`;
  if (!realtimeData.meta.runtime_enabled) return '实时运行时未启用 · 当前可手动按需直连 MooTDX';
  if (realtimeData.quote) return `盘中缓存 · ${formatQuoteTime(realtimeData.quote.quote_time)}`;
  return '盘中缓存暂不可用 · 等待下一轮刷新';
});

const activeChartOption = computed<EChartsOption>(() => {
  if (activeChart.value === 'daily') return dailyChartOption.value;
  if (activeChart.value === 'minute') return minuteChartOption(minuteBars.value?.items || [], minuteBars.value?.reference_price || null);
  return minuteChartOption(realtime.value?.minute_bars || [], latestQuote.value?.pre_close_price || null);
});
const activeChartEmpty = computed(() => {
  if (activeChart.value === 'daily') return !(dailyBars.value?.items.length);
  if (activeChart.value === 'minute') return !(minuteBars.value?.items.length);
  return !(realtime.value?.minute_bars.length);
});
const chartEmptyText = computed(() => {
  if (activeChart.value === 'daily') return '暂无日 K 数据，请确认 daily_close_core_ingest 已沉淀';
  if (activeChart.value === 'minute') return '暂无历史分钟线，请确认当日分钟线已沉淀';
  return '暂无实时分时数据，MooTDX 或 AkShare 当前未返回';
});

const dailyChartOption = computed<EChartsOption>(() => {
  const items = dailyBars.value?.items || [];
  const dates = items.map((item) => item.trade_date);
  const candles = items.map((item) => [item.open_price, item.close_price, item.low_price, item.high_price]);
  const volume = coloredVolume(items.map((item) => ({ price: item.close_price, volume: item.volume_hand })), items[0]?.pre_close_price || null);
  return {
    animation: false,
    tooltip: { trigger: 'axis' },
    grid: [{ left: 54, right: 18, top: 24, height: 260 }, { left: 54, right: 18, top: 310, height: 70 }],
    xAxis: [{ type: 'category', data: dates, boundaryGap: true }, { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } }],
    yAxis: [{ scale: true }, { gridIndex: 1, splitNumber: 2 }],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    series: [
      { name: '日K', type: 'candlestick', data: candles, itemStyle: { color: '#d92d20', color0: '#07845f', borderColor: '#d92d20', borderColor0: '#07845f' } },
      { name: 'MA5', type: 'line', smooth: true, showSymbol: false, data: items.map((item) => item.ma5), lineStyle: { color: '#f59e0b' } },
      { name: 'MA10', type: 'line', smooth: true, showSymbol: false, data: items.map((item) => item.ma10), lineStyle: { color: '#2563eb' } },
      { name: 'MA20', type: 'line', smooth: true, showSymbol: false, data: items.map((item) => item.ma20), lineStyle: { color: '#7c3aed' } },
      { name: 'MA30', type: 'line', smooth: true, showSymbol: false, data: items.map((item) => item.ma30), lineStyle: { color: '#0f766e' } },
      { name: 'MA60', type: 'line', smooth: true, showSymbol: false, data: items.map((item) => item.ma60), lineStyle: { color: '#be123c' } },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volume, itemStyle: { color: '#8da2b5' } },
    ],
  };
});

const fundFlowOption = computed<EChartsOption>(() => {
  const items = fundWindowItems.value;
  let cumulative = 0;
  const cumulativeMainNet = items.map((item) => {
    cumulative += Number(item.main_net_inflow || 0);
    return cumulative;
  });
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 58, right: 16, top: 36, bottom: 36 },
    xAxis: { type: 'category', data: items.map((item) => item.trade_date) },
    yAxis: { type: 'value', axisLabel: { formatter: (value: number) => formatMoney(value) } },
    series: [
      {
        name: '主力净流入',
        type: 'bar',
        data: items.map((item) => ({
          value: item.main_net_inflow || 0,
          itemStyle: { color: Number(item.main_net_inflow || 0) >= 0 ? '#d92d20' : '#07845f' },
        })),
      },
      { name: '累计主力净额', type: 'line', smooth: true, data: cumulativeMainNet, itemStyle: { color: '#2563eb' } },
    ],
  };
});

const minuteFactorOption = computed<EChartsOption>(() => {
  const items = factors.value?.minute_factors || [];
  const labels = items.map((item) => formatBarTime(item.bar_time));
  const volumeSpikes = items.map((item) => {
    const value = item.volume_spike_ratio;
    if (value === null || value === undefined) return null;
    return {
      value,
      itemStyle: { color: value >= 1.5 ? '#d92d20' : value >= 1 ? '#f59e0b' : '#98a2b3' },
    };
  });
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: [{ left: 54, right: 18, top: 34, height: 142 }, { left: 54, right: 18, top: 212, height: 56 }],
    xAxis: [
      { type: 'category', data: labels, boundaryGap: false, axisLabel: { show: false } },
      { type: 'category', data: labels, gridIndex: 1, axisLabel: { interval: 29 } },
    ],
    yAxis: [
      { type: 'value', name: '收益%', axisLabel: { formatter: (value: number) => `${value}%` } },
      { type: 'value', gridIndex: 1, name: '倍数', min: 0, splitNumber: 2, axisLabel: { formatter: (value: number) => `${value}x` } },
    ],
    series: [
      { name: '分钟收益', type: 'line', showSymbol: false, data: items.map((item) => item.minute_return), lineStyle: { color: '#d92d20', width: 2 }, areaStyle: { color: 'rgba(217, 45, 32, 0.08)' } },
      {
        name: '放量倍数', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumeSpikes,
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#98a2b3', type: 'dashed' }, label: { formatter: '20分钟均量' }, data: [{ yAxis: 1 }] },
      },
    ],
  };
});

const limitColumns: DataTableColumns<StockLimitEvent> = [
  { title: '日期', key: 'trade_date', width: 110 },
  { title: '类型', key: 'event_type', width: 100 },
  { title: '收盘', key: 'close_price', width: 100, render: (row) => formatNumber(row.close_price) },
  { title: '开板', key: 'open_count', width: 90, render: (row) => row.open_count ?? '-' },
];

const lhbColumns: DataTableColumns<StockLhbEvent> = [
  { title: '日期', key: 'trade_date', width: 110 },
  { title: '原因', key: 'reason', minWidth: 220 },
  { title: '净买入', key: 'net_buy_amount', width: 120, render: (row) => h('span', { class: numberClass(row.net_buy_amount) }, formatMoney(row.net_buy_amount)) },
];

const announcementColumns: DataTableColumns<StockAnnouncement> = [
  { title: '发布时间', key: 'published_at', width: 160, render: (row) => formatDateTime(row.published_at) },
  { title: '类别', key: 'category', width: 100, render: (row) => row.category || '-' },
  { title: '标题', key: 'title', minWidth: 260, render: (row) => row.url ? h('a', { href: row.url, target: '_blank', rel: 'noreferrer' }, row.title) : row.title },
];

async function loadAll() {
  if (!currentStockCode.value) return;
  loading.value = true;
  try {
    await Promise.all([
      loadOverview(),
      loadRealtime(),
      loadDailyBars(),
      loadFundFlow(),
      loadEvents(),
    ]);
    await loadMinuteBars();
  } catch (error) {
    message.error(error instanceof Error ? error.message : '加载个股行情失败');
  } finally {
    loading.value = false;
  }
}

async function loadOverview() {
  overview.value = await marketDataApi.stockAnalysisOverview(currentStockCode.value);
  if (overview.value.stock.status !== 'active') autoRefresh.value = false;
}

async function loadRealtime() {
  chartLoading.value = activeChart.value === 'realtime';
  try {
    realtime.value = await marketDataApi.stockAnalysisRealtime(currentStockCode.value);
    if (activeChart.value === 'realtime' && !realtime.value.meta.market_session) {
      activeChart.value = 'daily';
    }
  } finally {
    chartLoading.value = false;
  }
}

async function loadDailyBars() {
  dailyBars.value = await marketDataApi.stockAnalysisDailyBars(currentStockCode.value, { limit: 250 });
}

async function loadMinuteBars(selectedTradeDate?: string | null) {
  const requestedTradeDate = selectedTradeDate ?? minuteTradeDate.value;
  const result = await marketDataApi.stockAnalysisMinuteBars(currentStockCode.value, {
    tradeDate: requestedTradeDate || undefined,
    limit: 300,
  });
  minuteBars.value = result;
  if (result.trade_date) minuteTradeDate.value = result.trade_date;
  await loadFactors(result.trade_date || requestedTradeDate || undefined);
}

async function loadFactors(tradeDate?: string) {
  factors.value = await marketDataApi.stockAnalysisFactors(currentStockCode.value, { tradeDate, lookback: 120 });
}

async function loadFundFlow() {
  fundFlow.value = await marketDataApi.stockAnalysisFundFlow(currentStockCode.value, { lookback: 80 });
}

async function loadEvents() {
  events.value = await marketDataApi.stockAnalysisEvents(currentStockCode.value, { lookback: 60 });
}

async function searchStocks() {
  const keyword = searchKeyword.value.trim();
  if (!keyword) {
    searchItems.value = [];
    return;
  }
  searchLoading.value = true;
  try {
    searchItems.value = (await marketDataApi.stockAnalysisSearch({ keyword, limit: 20 })).items;
  } catch (error) {
    message.error(error instanceof Error ? error.message : '搜索股票失败');
  } finally {
    searchLoading.value = false;
  }
}

function openStock(code: string) {
  currentStockCode.value = code;
  searchItems.value = [];
  searchKeyword.value = '';
  minuteTradeDate.value = null;
  void router.replace({ path: '/market', query: { stock_code: code } });
  void loadAll();
}

function minuteChartOption(items: StockMinuteBar[], referencePrice: number | null): EChartsOption {
  const labels = items.map((item) => formatBarTime(item.bar_time));
  const hasAveragePrice = items.some((item) => item.avg_price !== null && item.avg_price !== undefined);
  const prices = items.map((item) => item.price);
  const reference = referencePrice ?? prices.find((value) => value !== null && value !== undefined) ?? null;
  const ma5 = rollingAverage(prices, 5);
  const ma10 = rollingAverage(prices, 10);
  const volume = coloredVolume(items.map((item) => ({ price: item.price, volume: item.volume_hand })), reference);
  const priceValues = prices.filter((value): value is number => value !== null && value !== undefined);
  const priceRange = chartPriceRange(priceValues, reference);
  return {
    animation: false,
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: [{ left: 54, right: 18, top: 34, height: 270 }, { left: 54, right: 18, top: 330, height: 62 }],
    xAxis: [
      { type: 'category', data: labels, boundaryGap: false },
      { type: 'category', data: labels, gridIndex: 1, axisLabel: { show: false } },
    ],
    yAxis: [
      { scale: true, min: priceRange.min, max: priceRange.max },
      {
        scale: true,
        min: priceRange.min,
        max: priceRange.max,
        position: 'right',
        axisLabel: { formatter: (value: number) => reference ? `${(((value - reference) / reference) * 100).toFixed(2)}%` : '' },
        splitLine: { show: false },
      },
      { gridIndex: 1, splitNumber: 2 },
    ],
    series: [
      {
        name: '分时价格',
        type: 'line',
        showSymbol: false,
        smooth: true,
        data: prices,
        lineStyle: { color: '#2563eb', width: 2 },
        markLine: reference ? { silent: true, symbol: 'none', lineStyle: { color: '#98a2b3', type: 'dashed' }, label: { formatter: `昨收 ${formatNumber(reference)}` }, data: [{ yAxis: reference }] } : undefined,
      },
      { name: '分钟MA5', type: 'line', showSymbol: false, smooth: true, data: ma5, lineStyle: { color: '#f59e0b' } },
      { name: '分钟MA10', type: 'line', showSymbol: false, smooth: true, data: ma10, lineStyle: { color: '#7c3aed' } },
      ...(hasAveragePrice ? [{ name: '均价', type: 'line' as const, showSymbol: false, smooth: true, data: items.map((item) => item.avg_price), lineStyle: { type: 'dashed' as const, color: '#f59e0b' } }] : []),
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 2, data: volume },
    ],
  };
}

function startAutoRefresh() {
  stopAutoRefresh();
  if (!autoRefresh.value || activeChart.value !== 'realtime') return;
  const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
  const topic = `stock:${currentStockCode.value}`;
  realtimeEventSource = new EventSource(`${apiBaseUrl}/realtime/stream?topics=${encodeURIComponent(topic)}`);
  realtimeEventSource.addEventListener(topic, (event) => {
    if (document.visibilityState !== 'visible') return;
    try {
      realtime.value = JSON.parse((event as MessageEvent<string>).data) as StockAnalysisRealtime;
    } catch {
      void loadRealtime();
    }
  });
  realtimeEventSource.onerror = () => {
    realtimeEventSource?.close();
    realtimeEventSource = null;
    if (!refreshTimer) {
      refreshTimer = window.setInterval(() => {
        if (document.visibilityState === 'visible') void loadRealtime();
      }, 60000);
    }
  };
}

function stopAutoRefresh() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  realtimeEventSource?.close();
  realtimeEventSource = null;
}

function featureValue(key: string) {
  return latestDailyFactor.value?.features?.[key] ?? null;
}

function featureNumber(key: string) {
  const value = featureValue(key);
  return typeof value === 'number' ? value : null;
}

function technicalValue(key: string) {
  const tech = latestDailyFactor.value?.features?.tushare_technical;
  if (tech && typeof tech === 'object' && key in tech) {
    return (tech as Record<string, unknown>)[key];
  }
  const raw = factors.value?.latest.technical_factor?.factors?.[key];
  return raw ?? null;
}

function technicalNumber(key: 'macd' | 'rsi6' | 'kdj' | 'bollUpper' | 'atr') {
  const sourceKey: Record<typeof key, string> = {
    macd: 'macd_bfq',
    rsi6: 'rsi_bfq_6',
    kdj: 'kdj_bfq',
    bollUpper: 'boll_upper_bfq',
    atr: 'atr_bfq',
  };
  const value = technicalValue(sourceKey[key]);
  return typeof value === 'number' ? value : null;
}

function formatUnknown(value: unknown) {
  if (typeof value === 'number') return formatNumber(value);
  if (value === null || value === undefined || value === '') return '-';
  return String(value);
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits });
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return `${formatNumber(value)}%`;
}

function formatRatioPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return `${formatNumber(value * 100)}%`;
}

function formatDays(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return `${Math.round(value)} 日`;
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  const abs = Math.abs(value);
  if (abs >= 100000000) return `${formatNumber(value / 100000000)}亿`;
  if (abs >= 10000) return `${formatNumber(value / 10000)}万`;
  return formatNumber(value);
}

function formatMoneyFromWan(value: number | null | undefined) {
  if (value === null || value === undefined) return '-';
  return formatMoney(value * 10000);
}

function formatBarTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(11, 16);
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(parsed);
}

function formatQuoteTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 16);
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.replace('T', ' ').slice(0, 16);
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
}

function rollingAverage(values: Array<number | null>, windowSize: number) {
  let sum = 0;
  const output: Array<number | null> = [];
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index] ?? 0;
    sum += value;
    if (index >= windowSize) sum -= values[index - windowSize] ?? 0;
    output.push(index >= windowSize - 1 ? Number((sum / windowSize).toFixed(4)) : null);
  }
  return output;
}

function coloredVolume(items: Array<{ price: number | null; volume: number | null }>, referencePrice: number | null) {
  let previousPrice = referencePrice;
  return items.map((item) => {
    const isUp = item.price !== null && item.price !== undefined && (previousPrice === null || previousPrice === undefined || item.price >= previousPrice);
    if (item.price !== null && item.price !== undefined) previousPrice = item.price;
    return {
      value: item.volume || 0,
      itemStyle: { color: isUp ? '#d92d20' : '#07845f' },
    };
  });
}

function chartPriceRange(values: number[], referencePrice: number | null) {
  const candidates = referencePrice === null ? values : [...values, referencePrice];
  if (!candidates.length) return { min: undefined, max: undefined };
  const low = Math.min(...candidates);
  const high = Math.max(...candidates);
  const padding = Math.max((high - low) * 0.08, low * 0.004);
  return { min: Number((low - padding).toFixed(4)), max: Number((high + padding).toFixed(4)) };
}

function numberTone(value: number | null | undefined) {
  if (value === null || value === undefined) return '';
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return '';
}

function numberClass(value: number | null | undefined) {
  return numberTone(value);
}

function statusText(status: string) {
  const map: Record<string, string> = { active: '正常', suspended: '暂停上市', delisted: '退市', excluded: '排除' };
  return map[status] || status;
}

watch([autoRefresh, activeChart], startAutoRefresh);
watch(() => route.query.stock_code, (value) => {
  const code = String(value || '');
  if (code && code !== currentStockCode.value) {
    currentStockCode.value = code;
    void loadAll();
    startAutoRefresh();
  }
});

watch(currentStockCode, startAutoRefresh);

onMounted(() => {
  void loadAll();
});

onBeforeUnmount(stopAutoRefresh);
</script>

<style scoped>
.market-page {
  padding: 22px;
}

.market-header,
.stock-title-band,
.chart-toolbar,
.panel-title,
.header-actions,
.stock-search {
  display: flex;
  align-items: center;
  gap: 12px;
}

.market-header,
.stock-title-band {
  justify-content: space-between;
  margin-bottom: 14px;
}

.stock-search {
  position: relative;
  width: min(620px, 100%);
}

.stock-search .n-input {
  flex: 1;
}

.search-results {
  position: absolute;
  top: 42px;
  left: 0;
  z-index: 20;
  width: min(520px, calc(100vw - 48px));
  max-height: 340px;
  overflow: auto;
  border: 1px solid #d8e0e5;
  background: #fff;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.14);
}

.search-results button {
  width: 100%;
  min-height: 42px;
  border: 0;
  border-bottom: 1px solid #edf1f4;
  background: #fff;
  display: grid;
  grid-template-columns: 1fr 90px 72px;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  text-align: left;
  cursor: pointer;
}

.search-results button:hover {
  background: #eef7f4;
}

.stock-title-band {
  padding: 16px 18px;
  border: 1px solid #d8e0e5;
  background: #fff;
}

.stock-title-band h1 {
  margin: 0;
  font-size: 24px;
}

.stock-title-band p {
  margin: 7px 0 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: #667085;
}

.quote-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(92px, 1fr));
  gap: 10px;
  min-width: min(620px, 52vw);
}

.quote-strip div {
  border-left: 1px solid #e5eaee;
  padding-left: 14px;
}

.quote-strip span {
  display: block;
  color: #667085;
  font-size: 12px;
}

.quote-strip strong {
  display: block;
  margin-top: 4px;
  font-size: 20px;
}

.quote-strip .time-text {
  font-size: 14px;
}

.market-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 14px;
}

.analysis-grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.panel {
  min-width: 0;
  border: 1px solid #d8e0e5;
  background: #fff;
  padding: 14px;
}

.panel-title {
  justify-content: space-between;
  margin-bottom: 12px;
}

.panel-title h2 {
  margin: 0;
  font-size: 16px;
}

.panel-title span,
.muted-hint,
.warning-line {
  color: #667085;
  font-size: 12px;
}

.panel-title > div > span {
  display: block;
  margin-top: 3px;
}

.chart-toolbar {
  justify-content: space-between;
  margin-bottom: 10px;
}

.chart-context {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  margin: 0 0 10px;
  padding: 0 9px;
  border: 1px solid #d8e0e5;
  background: #f8fafb;
  color: #475467;
  font-size: 12px;
}

.chart-context.warning {
  border-color: #f2c96d;
  background: #fff8e5;
  color: #8a5a00;
}

.date-control {
  width: 170px;
}

.side-panel {
  display: grid;
  gap: 14px;
  align-content: start;
}

.info-grid {
  display: grid;
  grid-template-columns: 86px 1fr;
  gap: 8px 12px;
  margin: 0;
  font-size: 13px;
}

.info-grid dt {
  color: #667085;
}

.info-grid dd {
  margin: 0;
  font-weight: 600;
}

.snapshot-list {
  display: grid;
  gap: 8px;
}

.snapshot-list div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #edf1f4;
}

.sector-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 162px;
  overflow: auto;
}

.sector-tags a {
  color: #146b56;
  text-decoration: none;
  background: #e7f6f0;
  border-radius: 4px;
  padding: 4px 7px;
  font-size: 12px;
}

.factor-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.factor-section-label {
  margin: 14px 0 8px;
  color: #475467;
  font-size: 12px;
  font-weight: 700;
}

.factor-section-label:first-of-type {
  margin-top: 0;
}

:deep(.metric) {
  min-height: 54px;
  border: 1px solid #edf1f4;
  background: #f8fafb;
  padding: 8px;
}

:deep(.metric-copy) {
  display: grid;
  gap: 3px;
}

:deep(.metric-label) {
  display: block;
  color: #344054;
  font-size: 13px;
  font-weight: 700;
}

:deep(.metric-hint) {
  display: block;
  color: #667085;
  font-size: 11px;
}

:deep(.metric strong) {
  display: block;
  margin-top: 5px;
  font-size: 16px;
}

.fund-window-tabs {
  display: flex;
  gap: 6px;
}

.fund-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0 0 12px;
  padding: 10px 0;
  border-top: 1px solid #edf1f4;
  border-bottom: 1px solid #edf1f4;
}

.fund-summary span {
  display: block;
  color: #667085;
  font-size: 12px;
}

.fund-summary strong {
  display: block;
  margin-top: 4px;
  font-size: 16px;
}

.events-panel {
  margin-top: 14px;
}

.events-grid {
  display: grid;
  grid-template-columns: 0.8fr 1.2fr 1.4fr;
  gap: 12px;
  overflow-x: auto;
}

.up {
  color: #d92d20;
}

.down {
  color: #07845f;
}

.warning-line {
  margin-top: 8px;
}

@media (max-width: 1180px) {
  .market-grid,
  .analysis-grid {
    grid-template-columns: 1fr;
  }

  .quote-strip {
    min-width: 0;
    width: 100%;
  }
}

@media (max-width: 760px) {
  .market-page {
    padding: 12px;
  }

  .market-header,
  .stock-title-band {
    align-items: stretch;
    flex-direction: column;
  }

  .stock-search,
  .header-actions,
  .chart-toolbar {
    width: 100%;
  }

  .quote-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .factor-grid {
    grid-template-columns: 1fr;
  }

  .events-grid {
    grid-template-columns: repeat(3, minmax(280px, 1fr));
  }
}
</style>
