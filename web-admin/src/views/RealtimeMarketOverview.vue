<template>
  <main class="workspace realtime-overview-page">
    <header class="topbar">
      <div>
        <div class="eyebrow">盘中研究驾驶舱</div>
        <h1>实时市场总览</h1>
        <p>同一轮全市场 Quote 聚合；概念题材、申万行业与股票池严格分层，不把盘中事实伪装成盘后情绪结论。</p>
      </div>
      <div class="header-actions">
        <div class="round-meta">
          <span>轮次 {{ overview?.round_id || '尚未形成' }}</span>
          <strong>{{ formatDateTime(overview?.as_of) }}</strong>
        </div>
        <n-tag :type="freshnessTagType" :bordered="false">{{ freshnessLabel }}</n-tag>
        <n-button secondary :loading="loading" @click="loadDashboard(false)">
          <template #icon><RefreshCw :size="16" /></template>
          刷新缓存
        </n-button>
      </div>
    </header>

    <n-alert v-if="errorMessage" class="page-alert" type="warning" :show-icon="true">{{ errorMessage }}</n-alert>
    <n-alert v-else-if="!runtime?.enabled" class="page-alert" type="info" :show-icon="true">
      实时服务尚未启用。页面只展示统一缓存，启用后会在交易时段自动形成市场轮次。
    </n-alert>
    <n-alert v-else-if="runtime?.market?.degraded" class="page-alert" type="warning" :show-icon="true">
      本轮市场数据处于降级状态：{{ runtime.market.degraded_reason || '覆盖率或上游响应未达到替换阈值' }}。页面保留最后一份完整快照。
    </n-alert>

    <n-spin :show="loading && !overview">
      <section class="market-summary">
        <div class="summary-card primary">
          <span>市场宽度</span>
          <strong>{{ breadthLabel }}</strong>
          <small>上涨 {{ formatPercent(breadth?.up_ratio_pct) }} · 下跌 {{ formatPercent(breadth?.down_ratio_pct) }}</small>
        </div>
        <div class="summary-card">
          <span>上涨 / 下跌 / 平盘</span>
          <strong><i class="up">{{ formatInteger(overview?.items.up_count) }}</i> / <i class="down">{{ formatInteger(overview?.items.down_count) }}</i> / {{ formatInteger(overview?.items.flat_count) }}</strong>
          <small>仅沪深 active、非 ST 标的</small>
        </div>
        <div class="summary-card">
          <span>平均 / 中位涨跌</span>
          <strong><i :class="changeClass(overview?.items.average_change_pct)">{{ formatPercent(overview?.items.average_change_pct) }}</i> / <i :class="changeClass(overview?.items.median_change_pct)">{{ formatPercent(overview?.items.median_change_pct) }}</i></strong>
          <small>中位数避免少数极端个股放大观感</small>
        </div>
        <div class="summary-card">
          <span>全市场成交额</span>
          <strong>{{ formatAmount(overview?.items.total_amount_yuan) }}</strong>
          <small>当日累计成交额</small>
        </div>
        <div class="summary-card coverage-card">
          <span>Quote 覆盖率</span>
          <strong>{{ formatPercent(overview?.items.coverage_pct) }}</strong>
          <n-progress type="line" :percentage="Number(overview?.items.coverage_pct || 0)" :show-indicator="false" :height="6" />
          <small>{{ formatInteger(overview?.items.quote_count) }} / {{ formatInteger(overview?.items.expected_quote_count) }} 只</small>
        </div>
        <div class="summary-card">
          <span>涨停 / 跌停</span>
          <strong v-if="limitEvents?.available"><i class="up">{{ formatInteger(limitEvents.limit_up_count) }}</i> / <i class="down">{{ formatInteger(limitEvents.limit_down_count) }}</i></strong>
          <strong v-else>未验证</strong>
          <small>{{ limitEvents?.available ? '以数据源返回的涨跌停价校验' : '当前 Quote 未提供可验证涨跌停价' }}</small>
        </div>
        <div class="summary-card">
          <span>触及日内高 / 低</span>
          <strong><i class="up">{{ formatInteger(intradayStructure?.at_high_count) }}</i> / <i class="down">{{ formatInteger(intradayStructure?.at_low_count) }}</i></strong>
          <small>价格区间可比较 {{ formatInteger(intradayStructure?.range_comparable_count) }} 只</small>
        </div>
      </section>

      <section class="index-strip">
        <article v-for="index in overview?.items.core_indexes || []" :key="index.index_code" class="index-card">
          <span>{{ index.index_name }}</span>
          <strong :class="changeClass(index.quote?.change_pct)">{{ index.available ? formatPercent(index.quote?.change_pct) : '未返回' }}</strong>
          <small>{{ index.available ? formatPrice(index.quote?.last_price) : index.source_symbol }}</small>
        </article>
      </section>

      <section class="research-grid">
        <article class="surface breadth-surface">
          <div class="panel-heading">
            <div>
              <span class="panel-kicker">全市场扩散</span>
              <h2>盘中宽度轨迹</h2>
            </div>
            <span class="muted">每个点均来自一轮完整全市场 Quote</span>
          </div>
          <MarketChart :option="timelineChartOption" :empty="timeline.items.length < 2" empty-text="等待至少两轮有效市场快照" height="270px" />
          <div class="distribution-row">
            <div v-for="item in distributionItems" :key="item.label" :class="item.tone">
              <span>{{ item.label }}</span>
              <strong>{{ formatInteger(item.value) }}</strong>
            </div>
          </div>
        </article>

        <article class="surface event-surface">
          <div class="panel-heading">
            <div>
              <span class="panel-kicker">同轮变化</span>
              <h2>盘中异动事件</h2>
            </div>
            <span class="muted">仅排名、宽度、领涨切换</span>
          </div>
          <div v-if="recentEvents.length" class="event-list">
            <div v-for="event in recentEvents" :key="event.id" class="event-row" :class="`event-${event.severity}`">
              <span class="event-dot" />
              <div>
                <strong>{{ event.title }}</strong>
                <p>{{ event.detail }}</p>
              </div>
              <time>{{ formatClock(event.as_of) }}</time>
            </div>
          </div>
          <n-empty v-else size="small" description="首轮快照已建立，后续显著变化会记录在这里" />
        </article>
      </section>

      <section class="market-detail-grid">
        <article class="surface trend-surface">
          <div class="panel-heading">
            <div>
              <span class="panel-kicker">日频趋势参照</span>
              <h2>站上均线比例</h2>
            </div>
            <span class="muted">{{ factorTrend?.available ? `${factorTrend.reference_trade_date} 收盘因子` : '日频因子尚不可用' }}</span>
          </div>
          <div v-if="factorTrend?.available" class="trend-grid">
            <div v-for="item in trendItems" :key="item.label" class="trend-item">
              <span>{{ item.label }}</span>
              <strong :class="changeClass(item.value?.above_pct)">{{ formatPercent(item.value?.above_pct) }}</strong>
              <small>{{ formatInteger(item.value?.above_count) }} / {{ formatInteger(item.value?.comparable_count) }} 只</small>
            </div>
          </div>
          <n-empty v-else size="small" description="等待最近交易日的 MA5 / MA20 / MA60 因子" />
          <p class="panel-note">盘中最新价与最近一个已完成交易日 MA 比较；不是使用未收盘的当日 K 重新计算均线。</p>
        </article>

        <article class="surface structure-surface">
          <div class="panel-heading">
            <div>
              <span class="panel-kicker">日内价格结构</span>
              <h2>开盘后强弱</h2>
            </div>
            <span class="muted">{{ formatInteger(intradayStructure?.open_comparable_count) }} 只可比较</span>
          </div>
          <div class="structure-grid">
            <div><span>高于开盘</span><strong class="up">{{ formatInteger(intradayStructure?.above_open_count) }}</strong></div>
            <div><span>低于开盘</span><strong class="down">{{ formatInteger(intradayStructure?.below_open_count) }}</strong></div>
            <div><span>触及日内高</span><strong class="up">{{ formatInteger(intradayStructure?.at_high_count) }}</strong></div>
            <div><span>触及日内低</span><strong class="down">{{ formatInteger(intradayStructure?.at_low_count) }}</strong></div>
          </div>
          <p class="panel-note">仅对 Quote 同时具备最新价、开高低字段的股票统计；缺字段不会按阈值猜测。</p>
        </article>
      </section>

      <section class="rankings-grid">
        <article v-for="card in rankCards" :key="card.key" class="surface ranking-surface">
          <div class="panel-heading compact-heading">
            <div><span class="panel-kicker">全市场</span><h2>{{ card.title }}</h2></div>
            <span class="muted">Top {{ card.items.length }}</span>
          </div>
          <div v-if="card.items.length" class="stock-rank-list">
            <div v-for="(stock, index) in card.items" :key="stock.stock_code" class="stock-rank-row">
              <span class="stock-rank">{{ index + 1 }}</span>
              <div><strong>{{ stock.stock_name || stock.stock_code }}</strong><small>{{ stock.stock_code }}</small></div>
              <strong :class="card.tone === 'change' ? changeClass(stock.change_pct) : ''">{{ rankMetric(stock, card.metric) }}</strong>
              <small v-if="card.tone !== 'change'" :class="changeClass(stock.change_pct)">{{ formatPercent(stock.change_pct) }}</small>
            </div>
          </div>
          <n-empty v-else size="small" description="当前轮次没有可排序数据" />
        </article>
      </section>

      <section class="surface taxonomy-surface">
        <div class="panel-heading taxonomy-heading">
          <div>
            <span class="panel-kicker">横向观察</span>
            <h2>热点与观察范围</h2>
          </div>
          <span class="muted">概念是题材主层；申万行业是辅助分类；股票池是你的观察边界。</span>
        </div>

        <n-tabs v-model:value="activeTab" type="segment" animated>
          <n-tab-pane name="concept" tab="概念热点">
            <div class="taxonomy-content">
              <section class="rank-table-wrap">
                <table class="rank-table">
                  <thead>
                    <tr><th>热度</th><th>题材</th><th>涨跌 / 中位</th><th>上涨 / 下跌</th><th>成交额</th><th>覆盖</th><th>领涨股</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in conceptItems" :key="item.sector_code" :class="{ selected: selectedSectorCode === item.sector_code }" @click="selectSector(item.sector_code)">
                      <td><strong>#{{ item.rank || '-' }}</strong><small :class="rankChangeClass(item.rank_change)">{{ rankChangeLabel(item.rank_change) }}</small></td>
                      <td><strong>{{ item.sector_name }}</strong><small>{{ item.member_count }} 成分 · 热度 {{ formatScore(item.heat_score) }}</small></td>
                      <td><strong :class="changeClass(item.change_pct)">{{ formatPercent(item.change_pct) }}</strong><small>{{ formatPercent(item.median_change_pct) }}</small></td>
                      <td><span class="up">{{ item.up_count }}</span> / <span class="down">{{ item.down_count }}</span></td>
                      <td>{{ formatAmount(item.amount_yuan) }}</td>
                      <td><n-tag size="small" :type="confidenceTagType(item.confidence)" :bordered="false">{{ confidenceLabel(item.confidence) }}</n-tag><small>{{ formatPercent(item.coverage_pct) }}</small></td>
                      <td><strong>{{ item.leader?.stock_name || item.leader?.stock_code || '-' }}</strong><small :class="changeClass(item.leader?.change_pct)">{{ formatPercent(item.leader?.change_pct) }}</small></td>
                    </tr>
                  </tbody>
                </table>
                <n-empty v-if="!conceptItems.length" description="当前快照尚无同花顺概念成分聚合" />
              </section>
              <SectorInspector :sector="selectedSector" @open-detail="openSectorDetail" />
            </div>
          </n-tab-pane>

          <n-tab-pane name="industry" tab="申万行业">
            <div class="taxonomy-content">
              <section class="rank-table-wrap">
                <table class="rank-table">
                  <thead>
                    <tr><th>热度</th><th>行业</th><th>层级</th><th>涨跌 / 中位</th><th>上涨 / 下跌</th><th>成交额</th><th>领涨股</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in industryItems" :key="item.sector_code" :class="{ selected: selectedSectorCode === item.sector_code }" @click="selectSector(item.sector_code)">
                      <td><strong>#{{ item.rank || '-' }}</strong><small :class="rankChangeClass(item.rank_change)">{{ rankChangeLabel(item.rank_change) }}</small></td>
                      <td><strong>{{ item.sector_name }}</strong><small>{{ item.member_count }} 成分</small></td>
                      <td>{{ taxonomyLabel(item.taxonomy_kind) }}</td>
                      <td><strong :class="changeClass(item.change_pct)">{{ formatPercent(item.change_pct) }}</strong><small>{{ formatPercent(item.median_change_pct) }}</small></td>
                      <td><span class="up">{{ item.up_count }}</span> / <span class="down">{{ item.down_count }}</span></td>
                      <td>{{ formatAmount(item.amount_yuan) }}</td>
                      <td><strong>{{ item.leader?.stock_name || item.leader?.stock_code || '-' }}</strong><small :class="changeClass(item.leader?.change_pct)">{{ formatPercent(item.leader?.change_pct) }}</small></td>
                    </tr>
                  </tbody>
                </table>
                <n-empty v-if="!industryItems.length" description="尚未同步 TickFlow 申万标的池目录与成员，行业聚合暂不可用" />
              </section>
              <SectorInspector :sector="selectedSector" @open-detail="openSectorDetail" />
            </div>
          </n-tab-pane>

          <n-tab-pane name="pools" tab="我的股票池">
            <div v-if="poolItems.length" class="pool-grid">
              <article v-for="item in poolItems" :key="item.pool_code" class="pool-card">
                <div class="pool-card-head"><div><span>{{ item.pool_code }}</span><h3>{{ item.pool_name }}</h3></div><strong>{{ formatPercent(item.average_change_pct) }}</strong></div>
                <div class="pool-metrics"><span>覆盖 {{ formatPercent(item.coverage_pct) }}</span><span><b class="up">{{ item.up_count }}</b> 上 / <b class="down">{{ item.down_count }}</b> 下</span><span>成交 {{ formatAmount(item.amount_yuan) }}</span></div>
                <div class="pool-leaders"><span>领涨</span><strong v-for="leader in (item.leaders || []).slice(0, 3)" :key="leader.stock_code">{{ leader.stock_name || leader.stock_code }} <i :class="changeClass(leader.change_pct)">{{ formatPercent(leader.change_pct) }}</i></strong></div>
              </article>
            </div>
            <n-empty v-else description="暂无已启用股票池的实时聚合结果" />
          </n-tab-pane>
        </n-tabs>
      </section>
    </n-spin>
  </main>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref, watch, type PropType } from 'vue';
import type { EChartsOption } from 'echarts';
import { useRouter } from 'vue-router';
import { NAlert, NButton, NEmpty, NProgress, NSpin, NTabPane, NTabs, NTag, useMessage } from 'naive-ui';
import { RefreshCw } from 'lucide-vue-next';
import MarketChart from '@/components/MarketChart.vue';
import { realtimeMarketApi } from '@/api/realtime-market';
import type {
  RealtimeMarketEvent,
  RealtimeMarketEvents,
  RealtimeMarketOverview,
  RealtimeMarketQuote,
  RealtimeMarketTimeline,
  RealtimeMarketTrendBucket,
  RealtimePoolSummary,
  RealtimeRuntimeStatus,
  RealtimeSectorStrength,
} from '@/types/realtime-market';

const router = useRouter();
const message = useMessage();
const loading = ref(false);
const errorMessage = ref('');
const overview = ref<RealtimeMarketOverview | null>(null);
const timeline = ref<RealtimeMarketTimeline>({ as_of: null, round_id: null, trade_date: null, items: [] });
const events = ref<RealtimeMarketEvents>({ as_of: null, round_id: null, trade_date: null, items: [] });
const runtime = ref<RealtimeRuntimeStatus | null>(null);
const conceptItems = ref<RealtimeSectorStrength[]>([]);
const industryItems = ref<RealtimeSectorStrength[]>([]);
const poolItems = ref<RealtimePoolSummary[]>([]);
const activeTab = ref<'concept' | 'industry' | 'pools'>('concept');
const selectedSectorCode = ref<string | null>(null);
let eventSource: EventSource | null = null;
let fallbackTimer: number | null = null;

const selectedSector = computed(() => [...conceptItems.value, ...industryItems.value].find((item) => item.sector_code === selectedSectorCode.value) || null);
const breadth = computed(() => overview.value?.items.market_breadth);
const limitEvents = computed(() => overview.value?.items.limit_events);
const factorTrend = computed(() => overview.value?.items.daily_factor_trend);
const intradayStructure = computed(() => overview.value?.items.intraday_structure);
const recentEvents = computed(() => [...events.value.items].reverse().slice(0, 8));
const trendItems = computed<Array<{ label: string; value: RealtimeMarketTrendBucket | null | undefined }>>(() => [
  { label: '站上 MA5', value: factorTrend.value?.ma5 },
  { label: '站上 MA20', value: factorTrend.value?.ma20 },
  { label: '站上 MA60', value: factorTrend.value?.ma60 },
  { label: '三线之上', value: factorTrend.value?.above_all },
]);
const rankCards = computed<Array<{ key: string; title: string; items: RealtimeMarketQuote[]; metric: 'change_pct' | 'amount_yuan' | 'volume_hand'; tone: 'change' | 'amount' | 'volume' }>>(() => [
  { key: 'gainers', title: '涨幅榜', items: overview.value?.items.top_gainers || [], metric: 'change_pct', tone: 'change' },
  { key: 'losers', title: '跌幅榜', items: overview.value?.items.top_losers || [], metric: 'change_pct', tone: 'change' },
  { key: 'amount', title: '成交额榜', items: overview.value?.items.top_amount || [], metric: 'amount_yuan', tone: 'amount' },
  { key: 'volume', title: '成交量榜', items: overview.value?.items.top_volume || [], metric: 'volume_hand', tone: 'volume' },
]);
const distributionItems = computed(() => {
  const distribution = overview.value?.items.change_distribution || {};
  return [
    { label: '≥ 5%', value: distribution.up_5_pct, tone: 'positive' },
    { label: '3% ~ 5%', value: distribution.up_3_pct, tone: 'positive' },
    { label: '0% ~ 3%', value: distribution.up_0_to_3_pct, tone: 'positive-light' },
    { label: '平盘', value: distribution.flat, tone: 'neutral' },
    { label: '-3% ~ 0%', value: distribution.down_0_to_3_pct, tone: 'negative-light' },
    { label: '-5% ~ -3%', value: distribution.down_3_pct, tone: 'negative' },
    { label: '≤ -5%', value: distribution.down_5_pct, tone: 'negative' },
  ];
});
const breadthLabel = computed(() => ({ broadly_up: '上涨占优', broadly_down: '下跌占优', mixed: '涨跌均衡' })[String(breadth.value?.state)] || '等待快照');
const freshnessSeconds = computed(() => {
  if (!overview.value?.as_of) return null;
  const seconds = Math.floor((Date.now() - new Date(overview.value.as_of).getTime()) / 1000);
  return Number.isFinite(seconds) ? Math.max(0, seconds) : null;
});
const freshnessLabel = computed(() => freshnessSeconds.value === null ? '尚无缓存' : freshnessSeconds.value <= 90 ? `数据新鲜 · ${freshnessSeconds.value}s` : `缓存偏旧 · ${freshnessSeconds.value}s`);
const freshnessTagType = computed(() => freshnessSeconds.value === null ? 'default' : freshnessSeconds.value <= 90 ? 'success' : 'warning');
const timelineChartOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['上涨家数', '下跌家数'], right: 8, top: 0 },
  grid: { left: 42, right: 16, top: 34, bottom: 28 },
  xAxis: { type: 'category', boundaryGap: false, data: timeline.value.items.map((item) => formatClock(item.as_of)), axisLabel: { hideOverlap: true } },
  yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef2f5' } } },
  series: [
    { name: '上涨家数', type: 'line', showSymbol: false, smooth: true, data: timeline.value.items.map((item) => item.up_count), lineStyle: { color: '#d92d20', width: 2 }, areaStyle: { color: 'rgba(217,45,32,.08)' } },
    { name: '下跌家数', type: 'line', showSymbol: false, smooth: true, data: timeline.value.items.map((item) => item.down_count), lineStyle: { color: '#07845f', width: 2 }, areaStyle: { color: 'rgba(7,132,95,.06)' } },
  ],
}));

const SectorInspector = defineComponent({
  name: 'SectorInspector',
  props: { sector: { type: Object as PropType<RealtimeSectorStrength | null>, default: null } },
  emits: ['open-detail'],
  setup(props, { emit }) {
    const heatLabels: Record<string, string> = { change: '涨跌', breadth: '扩散', limit: '涨停', liquidity: '成交' };
    return () => {
      if (!props.sector) return h('aside', { class: 'sector-inspector empty-inspector' }, [h(NEmpty, { size: 'small', description: '选择一行查看热度构成与领涨股' })]);
      const sector = props.sector;
      return h('aside', { class: 'sector-inspector' }, [
        h('div', { class: 'inspector-head' }, [
          h('div', [h('span', { class: 'panel-kicker' }, sector.sector_type === 'concept' ? '题材详情' : '行业详情'), h('h3', sector.sector_name)]),
          sector.source === 'tushare' ? h(NButton, { size: 'small', secondary: true, onClick: () => emit('open-detail', sector) }, { default: () => '查看历史详情' }) : null,
        ]),
        h('div', { class: 'inspector-summary' }, [
          h('div', [h('span', '实时热度'), h('strong', formatScore(sector.heat_score))]),
          h('div', [h('span', '覆盖率'), h('strong', formatPercent(sector.coverage_pct))]),
          h('div', [h('span', '中位涨跌'), h('strong', { class: changeClass(sector.median_change_pct) }, formatPercent(sector.median_change_pct))]),
        ]),
        h('div', { class: 'heat-breakdown' }, Object.entries(sector.heat_breakdown || {}).map(([key, value]) => {
          const numericValue = Number(value);
          return h('div', [h('span', heatLabels[key] || key), h(NProgress, { type: 'line', percentage: Math.max(0, Math.min(100, numericValue * 3)), showIndicator: false, height: 5 }), h('strong', numericValue.toFixed(1))]);
        })),
        h('div', { class: 'inspector-list' }, [
          h('span', '领涨'),
          ...(sector.leaders || []).slice(0, 5).map((stock) => h('div', { key: stock.stock_code }, [h('strong', stock.stock_name || stock.stock_code), h('small', { class: changeClass(stock.change_pct) }, formatPercent(stock.change_pct))])),
        ]),
        h('p', { class: 'inspector-note' }, '热度由涨跌、上涨扩散、可验证涨跌停和成交额构成；不是新闻解释，也不是盘后情绪分。'),
      ]);
    };
  },
});

async function loadDashboard(silent = false) {
  if (!silent) loading.value = true;
  errorMessage.value = '';
  try {
    const [nextOverview, nextConcepts, nextIndustries, nextPools, nextTimeline, nextEvents, nextRuntime] = await Promise.all([
      realtimeMarketApi.marketOverview(), realtimeMarketApi.sectors('concept'), realtimeMarketApi.sectors('industry'), realtimeMarketApi.pools(), realtimeMarketApi.marketTimeline(), realtimeMarketApi.marketEvents(), realtimeMarketApi.status(),
    ]);
    overview.value = nextOverview;
    conceptItems.value = nextConcepts.items;
    industryItems.value = nextIndustries.items;
    poolItems.value = nextPools.items;
    timeline.value = nextTimeline;
    events.value = nextEvents;
    runtime.value = nextRuntime;
    ensureSelection();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取实时市场缓存失败';
    if (!silent) message.warning(errorMessage.value);
  } finally {
    if (!silent) loading.value = false;
  }
}

function ensureSelection() {
  const inActiveTab = activeTab.value === 'industry' ? industryItems.value : conceptItems.value;
  if (!selectedSectorCode.value || ![...conceptItems.value, ...industryItems.value].some((item) => item.sector_code === selectedSectorCode.value)) {
    selectedSectorCode.value = inActiveTab[0]?.sector_code || conceptItems.value[0]?.sector_code || industryItems.value[0]?.sector_code || null;
  }
}

function selectSector(code: string) {
  selectedSectorCode.value = code;
}

function openSectorDetail(sector: RealtimeSectorStrength) {
  if (sector.source === 'tushare') void router.push(`/sectors/${encodeURIComponent(sector.sector_code)}`);
}

function applySectors(payload: { items?: RealtimeSectorStrength[] }) {
  const items = payload.items || [];
  conceptItems.value = items.filter((item) => item.sector_type === 'concept').sort((left, right) => (left.rank || 9999) - (right.rank || 9999));
  industryItems.value = items.filter((item) => item.sector_type === 'industry').sort((left, right) => (left.rank || 9999) - (right.rank || 9999));
  ensureSelection();
}

function startStream() {
  stopStream();
  const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
  const topics = 'market_overview,sectors,pools,market_timeline,market_events';
  eventSource = new EventSource(`${apiBaseUrl}/realtime/stream?topics=${encodeURIComponent(topics)}`);
  eventSource.addEventListener('market_overview', (event) => { overview.value = parseEvent<RealtimeMarketOverview>(event) || overview.value; });
  eventSource.addEventListener('sectors', (event) => { const payload = parseEvent<{ items?: RealtimeSectorStrength[] }>(event); if (payload) applySectors(payload); });
  eventSource.addEventListener('pools', (event) => { const payload = parseEvent<{ items?: RealtimePoolSummary[] }>(event); if (payload?.items) poolItems.value = payload.items; });
  eventSource.addEventListener('market_timeline', (event) => { timeline.value = parseEvent<RealtimeMarketTimeline>(event) || timeline.value; });
  eventSource.addEventListener('market_events', (event) => { events.value = parseEvent<RealtimeMarketEvents>(event) || events.value; });
  eventSource.onerror = () => {
    eventSource?.close();
    eventSource = null;
    if (fallbackTimer === null) fallbackTimer = window.setInterval(() => void loadDashboard(true), 60_000);
  };
}

function stopStream() {
  eventSource?.close();
  eventSource = null;
  if (fallbackTimer !== null) window.clearInterval(fallbackTimer);
  fallbackTimer = null;
}

function parseEvent<T>(event: Event): T | null {
  try { return JSON.parse((event as MessageEvent<string>).data) as T; } catch { return null; }
}

function formatInteger(value: number | null | undefined) { return typeof value === 'number' ? value.toLocaleString('zh-CN') : '-'; }
function formatPercent(value: number | null | undefined) { return typeof value === 'number' ? `${value.toFixed(2)}%` : '-'; }
function formatScore(value: number | null | undefined) { return typeof value === 'number' ? value.toFixed(1) : '-'; }
function formatPrice(value: number | null | undefined) { return typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '-'; }
function formatAmount(value: number | null | undefined) {
  if (typeof value !== 'number') return '-';
  const absolute = Math.abs(value);
  if (absolute >= 100_000_000) return `${(value / 100_000_000).toFixed(2)} 亿`;
  if (absolute >= 10_000) return `${(value / 10_000).toFixed(1)} 万`;
  return value.toFixed(0);
}
function formatVolume(value: number | null | undefined) {
  if (typeof value !== 'number') return '-';
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)} 亿手`;
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(2)} 万手`;
  if (Math.abs(value) >= 1) return `${value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} 手`;
  return value.toFixed(2);
}
function rankMetric(stock: RealtimeMarketQuote, metric: 'change_pct' | 'amount_yuan' | 'volume_hand') {
  if (metric === 'change_pct') return formatPercent(stock.change_pct);
  if (metric === 'amount_yuan') return formatAmount(stock.amount_yuan);
  return formatVolume(stock.volume_hand);
}
function formatDateTime(value: string | null | undefined) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'; }
function formatClock(value: string | null | undefined) { return value ? new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '-'; }
function changeClass(value: number | null | undefined) { return typeof value === 'number' && value > 0 ? 'up' : typeof value === 'number' && value < 0 ? 'down' : ''; }
function rankChangeLabel(value: number | null | undefined) { return typeof value !== 'number' || value === 0 ? '—' : value > 0 ? `↑${value}` : `↓${Math.abs(value)}`; }
function rankChangeClass(value: number | null | undefined) { return typeof value === 'number' && value > 0 ? 'up' : typeof value === 'number' && value < 0 ? 'down' : ''; }
function confidenceLabel(value: string) { return ({ high: '高覆盖', medium: '中覆盖', low: '低覆盖' })[value] || value; }
function confidenceTagType(value: string) { return value === 'high' ? 'success' : value === 'medium' ? 'warning' : 'error'; }
function taxonomyLabel(value: string | null | undefined) { return ({ sw1: '申万一级', sw2: '申万二级', sw3: '申万三级' })[String(value)] || '申万行业'; }

onMounted(() => { void loadDashboard(false); startStream(); });
onBeforeUnmount(stopStream);
watch(activeTab, () => {
  const items = activeTab.value === 'industry' ? industryItems.value : conceptItems.value;
  if (items.length && !items.some((item) => item.sector_code === selectedSectorCode.value)) selectedSectorCode.value = items[0].sector_code;
});
</script>

<style scoped>
.realtime-overview-page { padding: 22px 24px 32px; color: #17212b; }
.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 16px; }
.eyebrow, .panel-kicker { color: #1f8a70; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.topbar h1 { margin: 4px 0 0; font-size: 26px; line-height: 1.2; }
.topbar p { max-width: 800px; margin: 8px 0 0; color: #667085; line-height: 1.55; }
.header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.round-meta { display: grid; gap: 2px; text-align: right; font-size: 12px; color: #667085; }.round-meta strong { color: #344054; font-variant-numeric: tabular-nums; }
.page-alert { margin-bottom: 14px; }
.market-summary { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 12px; }
.summary-card, .index-card, .surface { border: 1px solid #dce5e9; background: #fff; box-shadow: 0 1px 2px rgba(16,24,40,.03); }
.summary-card { min-height: 112px; padding: 14px; display: grid; align-content: start; gap: 6px; border-radius: 8px; }
.summary-card.primary { background: linear-gradient(135deg, #effbf6, #ffffff 70%); border-color: #9bd8c5; }.summary-card span, .summary-card small { color: #667085; font-size: 12px; }.summary-card strong { color: #1d2939; font-size: 19px; line-height: 1.35; font-variant-numeric: tabular-nums; }.summary-card i, .pool-card i { font-style: normal; }.coverage-card :deep(.n-progress) { margin-top: 2px; }
.index-strip { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }.index-card { min-width: 0; border-radius: 7px; padding: 11px 12px; display: grid; gap: 4px; }.index-card span, .index-card small { overflow: hidden; color: #667085; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.index-card strong { font-size: 16px; }
.research-grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(360px, .9fr); gap: 14px; margin-top: 14px; }.surface { border-radius: 8px; padding: 15px; }.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }.panel-heading h2 { margin: 3px 0 0; font-size: 17px; }.muted { color: #667085; font-size: 12px; line-height: 1.5; }
.distribution-row { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 7px; margin-top: 10px; }.distribution-row div { display: grid; gap: 3px; min-width: 0; padding: 7px; border-left: 3px solid #d0d5dd; background: #f8fafb; }.distribution-row span { color: #667085; font-size: 11px; white-space: nowrap; }.distribution-row strong { font-variant-numeric: tabular-nums; }.distribution-row .positive { border-color: #d92d20; }.distribution-row .positive-light { border-color: #f79009; }.distribution-row .negative { border-color: #07845f; }.distribution-row .negative-light { border-color: #40a58a; }
.event-list { display: grid; max-height: 324px; overflow: auto; }.event-row { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; gap: 8px; align-items: start; padding: 10px 0; border-bottom: 1px solid #edf1f3; }.event-row:last-child { border-bottom: 0; }.event-row strong { font-size: 13px; }.event-row p { margin: 3px 0 0; color: #667085; font-size: 12px; line-height: 1.45; }.event-row time { color: #98a2b3; font-size: 11px; white-space: nowrap; }.event-dot { width: 7px; height: 7px; margin-top: 5px; border-radius: 50%; background: #98a2b3; }.event-positive .event-dot { background: #d92d20; }.event-negative .event-dot { background: #07845f; }
.market-detail-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(360px, .85fr); gap: 14px; margin-top: 14px; }.trend-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }.trend-item, .structure-grid div { display: grid; gap: 4px; padding: 10px; border: 1px solid #e4eaee; background: #f8fafb; }.trend-item span, .trend-item small, .structure-grid span { color: #667085; font-size: 12px; }.trend-item strong { font-size: 17px; }.structure-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }.structure-grid strong { font-size: 18px; }.panel-note { margin: 13px 0 0; color: #667085; font-size: 11px; line-height: 1.55; }
.rankings-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-top: 14px; }.compact-heading { margin-bottom: 8px; }.stock-rank-list { display: grid; }.stock-rank-row { display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; column-gap: 8px; align-items: center; min-height: 44px; border-bottom: 1px solid #edf1f3; }.stock-rank-row:last-child { border-bottom: 0; }.stock-rank-row > div { min-width: 0; display: grid; gap: 1px; }.stock-rank-row > div strong, .stock-rank-row > div small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.stock-rank-row > div small, .stock-rank-row > small { color: #98a2b3; font-size: 11px; }.stock-rank-row > strong { grid-column: 3; grid-row: 1; font-size: 13px; text-align: right; white-space: nowrap; }.stock-rank-row > small { grid-column: 3; grid-row: 2; text-align: right; }.stock-rank { color: #98a2b3; font-size: 12px; font-variant-numeric: tabular-nums; }
.taxonomy-surface { margin-top: 14px; }.taxonomy-heading { margin-bottom: 16px; }.taxonomy-content { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 14px; align-items: start; }.rank-table-wrap { overflow: auto; border: 1px solid #e4eaee; }.rank-table { width: 100%; min-width: 880px; border-collapse: collapse; font-size: 13px; }.rank-table th { padding: 10px; text-align: left; color: #667085; font-size: 12px; font-weight: 600; white-space: nowrap; background: #f8fafb; }.rank-table td { padding: 10px; border-top: 1px solid #edf1f3; vertical-align: middle; cursor: pointer; }.rank-table tbody tr:hover, .rank-table tbody tr.selected { background: #f2fbf7; }.rank-table td > strong, .rank-table td > small { display: block; }.rank-table td small { margin-top: 3px; color: #667085; font-size: 11px; }.rank-table td .up, .rank-table td .down { display: inline; }
.sector-inspector { min-height: 360px; padding: 14px; border: 1px solid #dce5e9; border-radius: 7px; background: #fbfdfd; }.empty-inspector { display: grid; place-items: center; }.inspector-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }.inspector-head h3 { max-width: 190px; margin: 3px 0 0; overflow: hidden; font-size: 17px; text-overflow: ellipsis; white-space: nowrap; }.inspector-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 16px; }.inspector-summary div { display: grid; gap: 3px; }.inspector-summary span, .inspector-list > span { color: #667085; font-size: 11px; }.inspector-summary strong { font-size: 14px; }.heat-breakdown { display: grid; gap: 8px; margin-top: 18px; }.heat-breakdown div { display: grid; grid-template-columns: 32px 1fr 30px; gap: 7px; align-items: center; font-size: 11px; color: #667085; }.heat-breakdown strong { color: #344054; text-align: right; font-variant-numeric: tabular-nums; }.inspector-list { display: grid; gap: 6px; margin-top: 18px; }.inspector-list div { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; }.inspector-list small { font-size: 12px; }.inspector-note { margin: 16px 0 0; color: #667085; font-size: 11px; line-height: 1.55; }
.pool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 12px; }.pool-card { border: 1px solid #dce5e9; border-radius: 7px; padding: 13px; background: #fbfdfd; }.pool-card-head { display: flex; justify-content: space-between; gap: 10px; }.pool-card-head span { color: #667085; font-size: 11px; }.pool-card-head h3 { margin: 3px 0 0; font-size: 16px; }.pool-card-head > strong { color: #d92d20; font-size: 16px; }.pool-metrics { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; color: #667085; font-size: 12px; }.pool-leaders { display: grid; gap: 5px; margin-top: 14px; padding-top: 11px; border-top: 1px solid #e7edef; }.pool-leaders > span { color: #667085; font-size: 11px; }.pool-leaders strong { display: flex; justify-content: space-between; font-size: 12px; }.pool-leaders i { font-style: normal; }
.up { color: #d92d20 !important; }.down { color: #07845f !important; }
@media (max-width: 1440px) { .market-summary { grid-template-columns: repeat(4, minmax(0, 1fr)); }.rankings-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 1280px) { .market-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }.index-strip { grid-template-columns: repeat(4, minmax(0, 1fr)); }.research-grid, .market-detail-grid { grid-template-columns: 1fr; }.taxonomy-content { grid-template-columns: 1fr; }.sector-inspector { min-height: 0; }.inspector-list { grid-template-columns: repeat(3, 1fr); }.inspector-list > span { grid-column: 1 / -1; } }
@media (max-width: 760px) { .realtime-overview-page { padding: 14px; }.topbar { flex-direction: column; }.header-actions { justify-content: flex-start; }.round-meta { text-align: left; }.market-summary { grid-template-columns: 1fr 1fr; }.index-strip { grid-template-columns: 1fr 1fr; }.distribution-row { grid-template-columns: repeat(3, 1fr); }.trend-grid { grid-template-columns: 1fr 1fr; }.rankings-grid { grid-template-columns: 1fr; }.taxonomy-heading { flex-direction: column; }.inspector-list { grid-template-columns: 1fr; }.inspector-list > span { grid-column: auto; } }
</style>
