<template>
  <main class="workspace sector-dashboard-page">
    <header class="topbar">
      <div>
        <h1>板块资金大屏</h1>
        <p>按即时资金流、涨跌幅和热度观察同花顺概念板块。</p>
      </div>
      <n-space>
        <n-switch v-model:value="autoRefresh">
          <template #checked>60 秒刷新</template>
          <template #unchecked>暂停刷新</template>
        </n-switch>
        <n-button secondary :loading="loading" @click="loadDashboard">
          <template #icon><RefreshCw :size="16" /></template>
          刷新
        </n-button>
      </n-space>
    </header>

    <section class="dashboard-surface">
      <div class="dashboard-toolbar">
        <n-select v-model:value="sortKey" size="small" :options="sortOptions" />
        <span class="muted">来源：{{ data?.source || '-' }}</span>
        <span class="muted">更新：{{ formatTime(data?.updated_at || null) }}</span>
      </div>
      <n-alert v-if="data?.warnings.length" type="warning" :show-icon="false">
        {{ data.warnings.join('；') }}
      </n-alert>

      <n-spin :show="loading">
        <div v-if="rankedItems.length" class="sector-card-grid">
          <button
            v-for="item in rankedItems"
            :key="item.sector_code || item.sector_name"
            type="button"
            class="sector-card"
            @click="openDetail(item.sector_code)"
          >
            <div class="card-head">
              <span class="rank">#{{ item.rank || '-' }}</span>
              <strong>{{ item.sector_name }}</strong>
              <n-tag size="small" :bordered="false" type="success">{{ item.component_count ?? '-' }} 股</n-tag>
            </div>
            <div class="metric-row">
              <span>主力净流入</span>
              <strong :class="numberClass(item.main_net_inflow)">{{ formatNumber(item.main_net_inflow) }}</strong>
            </div>
            <div class="metric-row">
              <span>涨跌幅</span>
              <strong :class="numberClass(item.change_pct)">{{ formatPercent(item.change_pct) }}</strong>
            </div>
            <div class="metric-row">
              <span>热度</span>
              <strong>{{ item.hot ? Math.round(item.hot).toLocaleString() : '-' }}</strong>
            </div>
            <div class="leader-line">领涨：{{ item.lead_stock || '-' }} <span>{{ formatPercent(item.lead_stock_pct_change) }}</span></div>
          </button>
        </div>
        <n-empty v-else description="暂无板块资金数据" />
      </n-spin>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { NAlert, NButton, NEmpty, NSelect, NSpace, NSpin, NSwitch, NTag, useMessage } from 'naive-ui';
import { RefreshCw } from 'lucide-vue-next';
import { marketDataApi } from '@/api/market-data';
import type { SectorDashboardData, SectorDashboardItem } from '@/types/market-data';

const router = useRouter();
const message = useMessage();
const loading = ref(false);
const autoRefresh = ref(true);
const sortKey = ref<'rank' | 'main_net_inflow' | 'change_pct' | 'hot'>('main_net_inflow');
const data = ref<SectorDashboardData | null>(null);
let timer: number | undefined;

const sortOptions = [
  { label: '主力净流入', value: 'main_net_inflow' },
  { label: '涨跌幅', value: 'change_pct' },
  { label: '热度', value: 'hot' },
  { label: '原始排名', value: 'rank' },
];

const rankedItems = computed(() => {
  const items = [...(data.value?.items || [])];
  return items.sort((left, right) => score(right, sortKey.value) - score(left, sortKey.value));
});

function score(item: SectorDashboardItem, key: typeof sortKey.value) {
  const value = item[key];
  return typeof value === 'number' ? value : Number.NEGATIVE_INFINITY;
}

async function loadDashboard() {
  loading.value = true;
  try {
    data.value = await marketDataApi.sectorDashboard({ sectorType: 'concept', limit: 50 });
  } catch (error) {
    message.error(error instanceof Error ? error.message : '加载板块资金大屏失败');
  } finally {
    loading.value = false;
  }
}

function resetTimer() {
  if (timer) window.clearInterval(timer);
  timer = undefined;
  if (autoRefresh.value) {
    timer = window.setInterval(() => void loadDashboard(), 60_000);
  }
}

function openDetail(sectorCode: string | null) {
  if (sectorCode) void router.push(`/sectors/${encodeURIComponent(sectorCode)}`);
}

function formatNumber(value: number | null) {
  if (typeof value !== 'number') return '-';
  const abs = Math.abs(value);
  if (abs >= 100000000) return `${(value / 100000000).toFixed(2)} 亿`;
  if (abs >= 10000) return `${(value / 10000).toFixed(2)} 万`;
  return value.toFixed(2);
}

function formatPercent(value: number | null) {
  return typeof value === 'number' ? `${value.toFixed(2)}%` : '-';
}

function numberClass(value: number | null) {
  return typeof value === 'number' && value > 0 ? 'up' : typeof value === 'number' && value < 0 ? 'down' : '';
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-';
}

watch(autoRefresh, resetTimer);
onMounted(() => {
  void loadDashboard();
  resetTimer();
});
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<style scoped>
.sector-dashboard-page { padding: 22px 24px 24px; }
.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
.topbar h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
.topbar p { margin: 6px 0 0; color: #667085; }
.dashboard-surface { min-height: calc(100vh - 150px); border: 1px solid #d8e0e5; background: #fff; padding: 16px; display: grid; gap: 12px; align-content: start; }
.dashboard-toolbar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.dashboard-toolbar :deep(.n-select) { width: 150px; }
.sector-card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.sector-card { border: 1px solid #d8e0e5; border-radius: 6px; background: #fff; padding: 12px; display: grid; gap: 9px; text-align: left; cursor: pointer; color: #1f2933; }
.sector-card:hover { border-color: #1f8a70; background: #f5fbf8; }
.card-head { min-width: 0; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 8px; }
.card-head strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rank { color: #667085; font-weight: 700; }
.metric-row { display: flex; justify-content: space-between; gap: 10px; color: #667085; }
.metric-row strong { color: #1f2933; }
.up { color: #d92d20 !important; }
.down { color: #07845f !important; }
.leader-line { color: #667085; font-size: 13px; }
.leader-line span { margin-left: 6px; }
.muted { color: #667085; font-size: 13px; }
@media (max-width: 760px) { .sector-dashboard-page { padding: 14px; } .topbar { flex-direction: column; } }
</style>
