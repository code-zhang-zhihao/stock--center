<template>
  <main class="workspace sector-page">
    <header class="topbar">
      <div>
        <h1>板块中心</h1>
        <p>浏览已同步的概念、行业板块及其当前成分股。</p>
      </div>
      <n-button secondary :loading="sectorLoading" @click="loadSectors">
        <template #icon><RefreshCw :size="16" /></template>
      </n-button>
    </header>

    <div class="sector-workspace">
      <section class="sector-list-panel">
        <div class="panel-heading">
          <span>板块目录</span>
          <span class="muted">{{ sectorTotal }} 个</span>
        </div>
        <n-tabs v-model:value="sectorType" type="segment" size="small">
          <n-tab-pane name="concept" tab="概念" />
          <n-tab-pane name="industry" tab="行业" />
        </n-tabs>

        <n-select v-model:value="provider" :options="providerOptions" size="small" />
        <div class="search-row list-search-row">
          <n-input v-model:value="keyword" clearable size="small" placeholder="搜索板块名称 / 代码" @keyup.enter="searchSectors" />
          <n-button quaternary circle title="搜索" @click="searchSectors">
            <template #icon><Search :size="16" /></template>
          </n-button>
        </div>

        <div class="sector-list-region">
          <n-spin class="sector-list-spin" :show="sectorLoading">
            <n-empty v-if="sectors.length === 0" description="没有符合条件的板块" />
            <div v-else class="sector-list">
              <div
                v-for="sector in sectors"
                :key="sector.sector_code"
                class="sector-row"
                :class="{ active: selectedCode === sector.sector_code }"
              >
                <button type="button" class="sector-select" @click="selectSector(sector.sector_code)">
                  <span class="sector-name">{{ sector.sector_name }}</span>
                  <span class="sector-meta">
                    <n-tag size="small" :bordered="false" :type="sourceTagType(sector.source)">{{ providerLabel(sector.source) }}</n-tag>
                    <strong>{{ sector.component_count }}</strong>
                  </span>
                </button>
                <n-button size="tiny" quaternary @click="openSectorDetail(sector.sector_code)">详情</n-button>
              </div>
            </div>
          </n-spin>
        </div>
        <div class="sector-list-footer">
          <n-pagination
            v-if="sectorTotal > sectorPageSize"
            v-model:page="sectorPage"
            :page-size="sectorPageSize"
            :item-count="sectorTotal"
            size="small"
            @update:page="loadSectors"
          />
          <span v-if="sectorTotal > 0" class="page-hint">每页 {{ sectorPageSize }} 条</span>
        </div>
      </section>

      <section class="stock-panel">
        <n-empty v-if="!selectedCode && !sectorLoading" description="从左侧选择一个板块" />
        <div v-else class="stock-content">
          <n-spin v-if="!stockData" class="stock-initial-loading" :show="stockLoading" />
          <template v-else>
            <div class="sector-detail-head">
              <div class="sector-detail-main">
                <div class="title-line">
                  <h2>{{ stockData.sector.sector_name }}</h2>
                  <n-tag size="small" :bordered="false" :type="sourceTagType(stockData.sector.source)">{{ providerLabel(stockData.sector.source) }}</n-tag>
                </div>
                <span class="mono muted">{{ stockData.sector.sector_code }}</span>
              </div>
              <div class="detail-stats">
                <span>当前成分</span>
                <strong>{{ stockData.total }}</strong>
              </div>
            </div>

            <div class="stock-toolbar">
              <n-input v-model:value="stockKeyword" clearable size="small" placeholder="搜索股票代码 / 名称" @keyup.enter="searchStocks" />
              <n-select v-model:value="stockStatus" size="small" :options="statusOptions" @update:value="searchStocks" />
              <n-button quaternary circle title="搜索成分股" @click="searchStocks">
                <template #icon><Search :size="16" /></template>
              </n-button>
            </div>

            <n-spin class="stock-table-region" :show="stockLoading">
              <n-data-table :columns="stockColumns" :data="stockData.items" :pagination="false" :max-height="stockTableMaxHeight" size="small" striped :row-key="stockRowKey" />
            </n-spin>
            <div class="stock-footer">
              <div class="stock-footer-info">
                <span class="muted">最近同步：{{ formatTime(stockData.sector.last_synced_at) }}</span>
                <span class="page-hint">显示 {{ stockRangeLabel }} / {{ stockData.total }}，每页 {{ stockPageSize }} 条</span>
              </div>
              <n-pagination
                v-if="stockData.total > stockPageSize"
                v-model:page="stockPage"
                :page-size="stockPageSize"
                :item-count="stockData.total"
                size="small"
                @update:page="loadStocks"
              />
            </div>
          </template>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NButton, NDataTable, NEmpty, NInput, NPagination, NSelect, NSpin, NTabPane, NTabs, NTag, useMessage, type DataTableColumns } from 'naive-ui';
import { RefreshCw, Search } from 'lucide-vue-next';
import { marketDataApi } from '@/api/market-data';
import type { BrowseSector, BrowseSectorStock, BrowseSectorStocks, SectorProvider, SectorType } from '@/types/market-data';

const route = useRoute();
const router = useRouter();
const message = useMessage();
const sectorType = ref<SectorType>(route.query.type === 'industry' ? 'industry' : 'concept');
const provider = ref<SectorProvider>(['tushare', 'akshare', 'all'].includes(String(route.query.provider)) ? route.query.provider as SectorProvider : 'tushare');
const keyword = ref(String(route.query.keyword || ''));
const selectedCode = ref(String(route.query.sector || ''));
const sectorPage = ref(1);
const sectorPageSize = 20;
const sectorTotal = ref(0);
const sectors = ref<BrowseSector[]>([]);
const sectorLoading = ref(false);
const stockData = ref<BrowseSectorStocks | null>(null);
const stockLoading = ref(false);
const stockKeyword = ref('');
const stockStatus = ref('');
const stockPage = ref(1);
const stockPageSize = 20;
const stockTableMaxHeight = ref(480);

const stockRangeLabel = computed(() => {
  if (!stockData.value || stockData.value.total === 0) return '0';
  const start = (stockData.value.page - 1) * stockData.value.page_size + 1;
  const end = Math.min(start + stockData.value.items.length - 1, stockData.value.total);
  return `${start}-${end}`;
});

const providerOptions = [
  { label: 'Tushare 同花顺', value: 'tushare' },
  { label: 'AkShare 历史来源', value: 'akshare' },
  { label: '全部来源', value: 'all' },
];
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '正常', value: 'active' },
  { label: '暂停', value: 'paused' },
  { label: '退市', value: 'delisted' },
];

const stockColumns = computed<DataTableColumns<BrowseSectorStock>>(() => [
  { title: '代码', key: 'stock_code', width: 100, render: (row) => h('span', { class: 'mono' }, row.stock_code) },
  { title: '名称', key: 'stock_name', minWidth: 130, render: (row) => row.stock_name || '待基础资料同步' },
  { title: '交易所', key: 'exchange', width: 86, render: (row) => row.exchange || '-' },
  { title: '行业', key: 'industry', minWidth: 120, render: (row) => row.industry || '-' },
  { title: '地区', key: 'area', width: 90, render: (row) => row.area || '-' },
  {
    title: '状态', key: 'status', width: 100,
    render: (row) => h(NTag, { size: 'small', bordered: false, type: row.stock_exists ? 'success' : 'warning' }, { default: () => row.stock_exists ? statusLabel(row.status) : '待同步' }),
  },
]);

function sourceTagType(source: string | null) {
  return source?.startsWith('tushare:') ? 'success' : source?.startsWith('akshare:') ? 'warning' : 'default';
}

function providerLabel(source: string | null) {
  if (source?.startsWith('tushare:')) return 'Tushare';
  if (source?.startsWith('akshare:')) return 'AkShare';
  return source || '未知来源';
}

function statusLabel(status: string | null) {
  return ({ active: '正常', paused: '暂停', delisted: '退市' } as Record<string, string>)[status || ''] || '-';
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-';
}

function stockRowKey(row: BrowseSectorStock) {
  return row.stock_code;
}

function updateStockTableHeight() {
  stockTableMaxHeight.value = Math.max(300, Math.min(720, window.innerHeight - 310));
}

async function syncRoute() {
  await router.replace({
    path: '/sectors',
    query: {
      type: sectorType.value,
      provider: provider.value,
      ...(keyword.value.trim() ? { keyword: keyword.value.trim() } : {}),
      ...(selectedCode.value ? { sector: selectedCode.value } : {}),
    },
  });
}

async function loadSectors() {
  sectorLoading.value = true;
  try {
    const page = await marketDataApi.browseSectors({
      sectorType: sectorType.value,
      provider: provider.value,
      keyword: keyword.value.trim(),
      page: sectorPage.value,
      pageSize: sectorPageSize,
    });
    sectors.value = page.items;
    sectorTotal.value = page.total;
    if (!page.items.some((item) => item.sector_code === selectedCode.value)) {
      selectedCode.value = page.items[0]?.sector_code || '';
      stockPage.value = 1;
    }
    await syncRoute();
    await loadStocks();
  } catch (error) {
    message.error(error instanceof Error ? error.message : '板块列表加载失败');
  } finally {
    sectorLoading.value = false;
  }
}

async function loadStocks() {
  if (!selectedCode.value) {
    stockData.value = null;
    return;
  }
  stockLoading.value = true;
  try {
    stockData.value = await marketDataApi.browseSectorStocks(selectedCode.value, {
      keyword: stockKeyword.value.trim(),
      status: stockStatus.value,
      page: stockPage.value,
      pageSize: stockPageSize,
    });
    await syncRoute();
  } catch (error) {
    message.error(error instanceof Error ? error.message : '成分股加载失败');
  } finally {
    stockLoading.value = false;
  }
}

function selectSector(sectorCode: string) {
  if (selectedCode.value === sectorCode) return;
  selectedCode.value = sectorCode;
  stockPage.value = 1;
  void loadStocks();
}

function openSectorDetail(sectorCode: string) {
  void router.push(`/sectors/${encodeURIComponent(sectorCode)}`);
}

function searchSectors() {
  sectorPage.value = 1;
  void loadSectors();
}

function searchStocks() {
  stockPage.value = 1;
  void loadStocks();
}

watch([sectorType, provider], () => {
  sectorPage.value = 1;
  selectedCode.value = '';
  void loadSectors();
});
onMounted(() => {
  updateStockTableHeight();
  window.addEventListener('resize', updateStockTableHeight);
  void loadSectors();
});
onBeforeUnmount(() => window.removeEventListener('resize', updateStockTableHeight));
</script>

<style scoped>
.sector-page { padding: 22px 24px 24px; }
.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
.topbar h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
.topbar p { margin: 6px 0 0; color: #667085; }
.sector-workspace { height: max(560px, calc(100vh - 148px)); display: grid; grid-template-columns: minmax(300px, 344px) minmax(0, 1fr); overflow: hidden; border: 1px solid #d8e0e5; background: #fff; }
.sector-list-panel, .stock-panel { height: 100%; min-width: 0; padding: 16px; box-sizing: border-box; }
.sector-list-panel { min-height: 0; border-right: 1px solid #d8e0e5; display: flex; flex-direction: column; gap: 10px; }
.panel-heading { display: flex; justify-content: space-between; align-items: baseline; color: #344054; font-size: 13px; font-weight: 700; }
.search-row, .stock-toolbar { display: flex; gap: 8px; align-items: center; }
.search-row :deep(.n-input), .stock-toolbar :deep(.n-input) { min-width: 0; flex: 1; }
.sector-list-region { min-height: 0; flex: 1; overflow-x: hidden; overflow-y: scroll; overscroll-behavior: contain; scrollbar-gutter: stable; }
.sector-list-spin, .sector-list-spin :deep(.n-spin-container) { height: auto; min-height: 100%; }
.sector-list { min-height: 100%; overflow: visible; border-top: 1px solid #edf1f3; border-bottom: 1px solid #edf1f3; }
.sector-row { width: 100%; min-height: 46px; border-bottom: 1px solid #edf1f3; padding: 5px 4px; background: transparent; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 6px; color: #1f2933; }
.sector-select { min-width: 0; min-height: 36px; border: 0; background: transparent; display: flex; justify-content: space-between; align-items: center; gap: 10px; text-align: left; color: inherit; cursor: pointer; }
.sector-row:hover, .sector-row.active { background: #e8f5f0; }
.sector-row.active { box-shadow: inset 3px 0 0 #1f8a70; }
.sector-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.sector-meta { flex: none; display: flex; align-items: center; gap: 7px; color: #667085; font-size: 12px; }
.sector-list-footer { flex: none; display: grid; gap: 5px; }
.stock-panel { min-height: 0; overflow: hidden; }
.stock-content { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
.stock-initial-loading { flex: 1; min-height: 0; }
.sector-detail-head { flex: none; display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; border-bottom: 1px solid #d8e0e5; padding: 2px 0 12px; }
.sector-detail-main { min-width: 0; }
.title-line { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.title-line h2 { margin: 0; font-size: 20px; letter-spacing: 0; }
.detail-stats { text-align: right; color: #667085; font-size: 12px; }
.detail-stats strong { display: block; color: #1f2933; font-size: 22px; line-height: 1.2; }
.stock-toolbar { flex: none; padding: 8px; border: 1px solid #e4e7ec; background: #f8fafc; }
.stock-toolbar :deep(.n-select) { width: 120px; flex: none; }
.stock-table-region { min-width: 0; min-height: 0; flex: 1; overflow: hidden; border: 1px solid #d8e0e5; }
.stock-table-region :deep(.n-spin-container) { height: 100%; min-height: 0; overflow: auto; }
.stock-footer { flex: none; min-height: 34px; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.stock-footer-info { display: grid; gap: 2px; min-width: 0; }
.page-hint { color: #98a2b3; font-size: 12px; }
@media (max-width: 900px) { .sector-page { padding: 14px; } .sector-workspace { height: auto; min-height: 0; grid-template-columns: 1fr; overflow: visible; } .sector-list-panel { height: 520px; border-right: 0; border-bottom: 1px solid #d8e0e5; } .stock-panel { min-height: 620px; } .stock-content { height: 620px; } .stock-toolbar :deep(.n-select) { width: 110px; } .stock-footer { align-items: flex-start; flex-direction: column; } }
</style>
