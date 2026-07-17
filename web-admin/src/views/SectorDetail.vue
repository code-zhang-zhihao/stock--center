<template>
  <main class="workspace sector-detail-page">
    <header class="topbar">
      <div>
        <h1>{{ overview?.sector.sector_name || '板块详情' }}</h1>
        <p>
          <span class="mono">{{ overview?.sector.sector_code || sectorCode }}</span>
          <n-tag v-if="overview" size="small" :bordered="false" type="success">{{ overview.taxonomy }}</n-tag>
        </p>
      </div>
      <n-space>
        <n-button secondary @click="router.push('/sectors')">返回板块中心</n-button>
        <n-button secondary :loading="loading" @click="loadAll">
          <template #icon><RefreshCw :size="16" /></template>
          刷新
        </n-button>
      </n-space>
    </header>

    <section class="search-strip">
      <n-input v-model:value="searchKeyword" clearable placeholder="搜索概念板块名称 / 代码" @keyup.enter="searchSectors">
        <template #prefix><Search :size="16" /></template>
      </n-input>
      <n-button secondary :loading="searchLoading" @click="searchSectors">搜索</n-button>
      <div v-if="searchItems.length" class="search-results">
        <button v-for="item in searchItems" :key="item.sector_code" type="button" @click="openSector(item.sector_code)">
          <span>{{ item.sector_name }}</span>
          <span class="mono">{{ item.sector_code }}</span>
        </button>
      </div>
    </section>

    <n-spin :show="loading">
      <div v-if="overview" class="detail-grid">
        <section class="panel chart-panel">
          <div class="panel-title">
            <h2>板块行情</h2>
            <span>ths_daily，最近 {{ bars.length }} 条</span>
          </div>
          <svg class="line-chart" viewBox="0 0 720 220" preserveAspectRatio="none">
            <polyline :points="barLinePoints" fill="none" stroke="#1f8a70" stroke-width="3" />
            <line x1="0" y1="190" x2="720" y2="190" stroke="#e4e7ec" />
          </svg>
          <div class="chart-summary">
            <span>最新收盘：{{ latestBar?.close ?? '-' }}</span>
            <span :class="numberClass(latestBar?.pct_change ?? null)">涨跌幅：{{ formatPercent(latestBar?.pct_change ?? null) }}</span>
          </div>
        </section>

        <section class="panel chart-panel">
          <div class="panel-title">
            <h2>资金流曲线</h2>
            <span>moneyflow_cnt_ths，单位：亿元</span>
          </div>
          <svg class="bar-chart" viewBox="0 0 720 220" preserveAspectRatio="none">
            <line x1="0" y1="110" x2="720" y2="110" stroke="#d8e0e5" />
            <rect
              v-for="bar in flowBars"
              :key="bar.key"
              :x="bar.x"
              :y="bar.y"
              :width="bar.width"
              :height="bar.height"
              :fill="bar.positive ? '#d92d20' : '#07845f'"
              opacity="0.82"
            />
          </svg>
          <div class="chart-summary">
            <span :class="numberClass(latestFlow?.net_amount ?? null)">净额：{{ latestFlow?.net_amount ?? '-' }} 亿</span>
            <span>领涨：{{ latestFlow?.lead_stock || '-' }} {{ formatPercent(latestFlow?.lead_pct_change ?? null) }}</span>
          </div>
        </section>

        <section class="panel leaders-panel">
          <div class="panel-title">
            <h2>领涨股</h2>
            <span>按资金流记录回溯</span>
          </div>
          <n-data-table :columns="leaderColumns" :data="leaders" :pagination="false" size="small" striped />
        </section>

        <section class="panel stocks-panel">
          <div class="panel-title">
            <h2>成分股</h2>
            <span>{{ stocks?.total || 0 }} 只</span>
          </div>
          <div class="stock-toolbar">
            <n-input v-model:value="stockKeyword" clearable size="small" placeholder="搜索股票代码 / 名称" @keyup.enter="searchStocks" />
            <n-select v-model:value="stockStatus" size="small" :options="statusOptions" @update:value="searchStocks" />
            <n-button quaternary circle title="搜索成分股" @click="searchStocks">
              <template #icon><Search :size="16" /></template>
            </n-button>
          </div>
          <n-data-table :columns="stockColumns" :data="stocks?.items || []" :pagination="false" size="small" striped />
          <div class="stock-footer">
            <span class="muted">显示 {{ stockRangeLabel }} / {{ stocks?.total || 0 }}，每页 {{ stockPageSize }} 条</span>
            <n-pagination
              v-if="(stocks?.total || 0) > stockPageSize"
              v-model:page="stockPage"
              :page-size="stockPageSize"
              :item-count="stocks?.total || 0"
              size="small"
              @update:page="loadStocks"
            />
          </div>
        </section>
      </div>
      <n-empty v-else description="没有找到板块详情" />
    </n-spin>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NButton, NDataTable, NEmpty, NInput, NPagination, NSelect, NSpace, NSpin, NTag, useMessage, type DataTableColumns } from 'naive-ui';
import { RefreshCw, Search } from 'lucide-vue-next';
import { marketDataApi } from '@/api/market-data';
import type { BrowseSector, BrowseSectorStock, BrowseSectorStocks, SectorAnalysisBar, SectorAnalysisOverview, SectorLeader, SectorMoneyFlowPoint } from '@/types/market-data';

const route = useRoute();
const router = useRouter();
const message = useMessage();
const sectorCode = ref(String(route.params.sectorCode || ''));
const loading = ref(false);
const searchLoading = ref(false);
const overview = ref<SectorAnalysisOverview | null>(null);
const bars = ref<SectorAnalysisBar[]>([]);
const flows = ref<SectorMoneyFlowPoint[]>([]);
const leaders = ref<SectorLeader[]>([]);
const stocks = ref<BrowseSectorStocks | null>(null);
const searchKeyword = ref('');
const searchItems = ref<BrowseSector[]>([]);
const stockKeyword = ref('');
const stockStatus = ref('');
const stockPage = ref(1);
const stockPageSize = 20;

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '正常', value: 'active' },
  { label: '暂停', value: 'paused' },
  { label: '退市', value: 'delisted' },
];

const latestBar = computed(() => bars.value[bars.value.length - 1] || null);
const latestFlow = computed(() => flows.value[flows.value.length - 1] || null);
const barLinePoints = computed(() => linePoints(bars.value.map((item) => item.close)));
const flowBars = computed(() => barRects(flows.value.map((item) => item.net_amount)));
const stockRangeLabel = computed(() => {
  if (!stocks.value || stocks.value.total === 0) return '0';
  const start = (stocks.value.page - 1) * stocks.value.page_size + 1;
  return `${start}-${Math.min(start + stocks.value.items.length - 1, stocks.value.total)}`;
});

const leaderColumns: DataTableColumns<SectorLeader> = [
  { title: '日期', key: 'trade_date', width: 110 },
  { title: '股票', key: 'stock_name', minWidth: 130 },
  { title: '代码', key: 'stock_code', width: 110, render: (row) => h('span', { class: 'mono' }, row.stock_code || '-') },
  { title: '涨跌幅', key: 'pct_change', width: 100, render: (row) => h('span', { class: numberClass(row.pct_change) }, formatPercent(row.pct_change)) },
];

const stockColumns: DataTableColumns<BrowseSectorStock> = [
  { title: '代码', key: 'stock_code', width: 100, render: (row) => h('span', { class: 'mono' }, row.stock_code) },
  { title: '名称', key: 'stock_name', minWidth: 130, render: (row) => row.stock_name || '待基础资料同步' },
  { title: '交易所', key: 'exchange', width: 86, render: (row) => row.exchange || '-' },
  { title: '行业', key: 'industry', minWidth: 120, render: (row) => row.industry || '-' },
  { title: '地区', key: 'area', width: 90, render: (row) => row.area || '-' },
  { title: '状态', key: 'status', width: 90, render: (row) => row.status || '-' },
];

async function loadAll() {
  if (!sectorCode.value) return;
  loading.value = true;
  try {
    const [overviewResult, barsResult, flowResult, leaderResult] = await Promise.all([
      marketDataApi.sectorOverview(sectorCode.value),
      marketDataApi.sectorBars(sectorCode.value, { limit: 120 }),
      marketDataApi.sectorMoneyFlow(sectorCode.value, { limit: 120 }),
      marketDataApi.sectorLeaders(sectorCode.value, { limit: 20 }),
    ]);
    overview.value = overviewResult;
    bars.value = barsResult.items;
    flows.value = flowResult.items;
    leaders.value = leaderResult.items;
    await loadStocks();
  } catch (error) {
    message.error(error instanceof Error ? error.message : '加载板块详情失败');
  } finally {
    loading.value = false;
  }
}

async function loadStocks() {
  if (!sectorCode.value) return;
  stocks.value = await marketDataApi.sectorAnalysisStocks(sectorCode.value, {
    keyword: stockKeyword.value.trim(),
    status: stockStatus.value,
    page: stockPage.value,
    pageSize: stockPageSize,
  });
}

async function searchSectors() {
  const keyword = searchKeyword.value.trim();
  if (!keyword) {
    searchItems.value = [];
    return;
  }
  searchLoading.value = true;
  try {
    searchItems.value = (await marketDataApi.searchSectorAnalysis({ keyword, limit: 20 })).items;
  } catch (error) {
    message.error(error instanceof Error ? error.message : '搜索板块失败');
  } finally {
    searchLoading.value = false;
  }
}

function openSector(code: string) {
  searchItems.value = [];
  void router.push(`/sectors/${encodeURIComponent(code)}`);
}

function searchStocks() {
  stockPage.value = 1;
  void loadStocks();
}

function linePoints(values: Array<number | null>) {
  const valid = values.map((value, index) => ({ value, index })).filter((item): item is { value: number; index: number } => typeof item.value === 'number');
  if (valid.length === 0) return '';
  const min = Math.min(...valid.map((item) => item.value));
  const max = Math.max(...valid.map((item) => item.value));
  const range = max - min || 1;
  const lastIndex = Math.max(values.length - 1, 1);
  return valid.map((item) => {
    const x = (item.index / lastIndex) * 720;
    const y = 190 - ((item.value - min) / range) * 160;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

function barRects(values: Array<number | null>) {
  const numeric = values.map((value) => typeof value === 'number' ? value : 0);
  const max = Math.max(...numeric.map((value) => Math.abs(value)), 1);
  const width = Math.max(2, 680 / Math.max(numeric.length, 1));
  return numeric.map((value, index) => {
    const height = Math.max(1, Math.abs(value) / max * 90);
    return {
      key: `${index}-${value}`,
      x: 20 + index * width,
      y: value >= 0 ? 110 - height : 110,
      width: Math.max(1, width - 1),
      height,
      positive: value >= 0,
    };
  });
}

function formatPercent(value: number | null) {
  return typeof value === 'number' ? `${value.toFixed(2)}%` : '-';
}

function numberClass(value: number | null) {
  return typeof value === 'number' && value > 0 ? 'up' : typeof value === 'number' && value < 0 ? 'down' : '';
}

watch(() => route.params.sectorCode, (value) => {
  sectorCode.value = String(value || '');
  void loadAll();
});
onMounted(loadAll);
</script>

<style scoped>
.sector-detail-page { padding: 22px 24px 24px; }
.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
.topbar h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
.topbar p { margin: 6px 0 0; color: #667085; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.search-strip { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; margin-bottom: 12px; }
.search-results { position: absolute; z-index: 10; top: 42px; left: 0; width: min(560px, 100%); border: 1px solid #d8e0e5; background: #fff; box-shadow: 0 12px 28px rgba(16, 24, 40, 0.12); }
.search-results button { width: 100%; border: 0; border-bottom: 1px solid #edf1f3; background: #fff; min-height: 38px; padding: 0 12px; display: flex; justify-content: space-between; gap: 12px; align-items: center; cursor: pointer; }
.search-results button:hover { background: #f5fbf8; }
.detail-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
.panel { border: 1px solid #d8e0e5; background: #fff; padding: 14px; min-width: 0; }
.panel-title { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 10px; }
.panel-title h2 { margin: 0; font-size: 17px; letter-spacing: 0; }
.panel-title span, .muted { color: #667085; font-size: 12px; }
.line-chart, .bar-chart { width: 100%; height: 220px; background: #f8fafc; border: 1px solid #edf1f3; }
.chart-summary { margin-top: 8px; display: flex; justify-content: space-between; gap: 12px; color: #667085; }
.stocks-panel { grid-column: 1 / -1; }
.stock-toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; padding: 8px; border: 1px solid #e4e7ec; background: #f8fafc; }
.stock-toolbar :deep(.n-input) { min-width: 0; flex: 1; }
.stock-toolbar :deep(.n-select) { width: 120px; flex: none; }
.stock-footer { min-height: 34px; margin-top: 10px; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.up { color: #d92d20; }
.down { color: #07845f; }
@media (max-width: 980px) { .sector-detail-page { padding: 14px; } .topbar { flex-direction: column; } .detail-grid { grid-template-columns: 1fr; } .stock-footer { align-items: flex-start; flex-direction: column; } }
</style>
