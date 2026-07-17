<template>
  <main class="workspace stock-pool-page">
    <header class="topbar">
      <div>
        <h1>股票池</h1>
        <p>管理系统池与自定义池；全市场范围由已同步的正常交易股票自动组成。</p>
      </div>
      <n-space>
        <n-button secondary :loading="loadingPools" @click="loadPools">
          <template #icon><RefreshCw :size="16" /></template>
        </n-button>
        <n-button type="primary" @click="openCreatePool">
          <template #icon><Plus :size="16" /></template>
          新建池
        </n-button>
      </n-space>
    </header>

    <div class="pool-workspace">
      <aside class="pool-list-panel">
        <div class="panel-heading">
          <span>股票池</span>
          <span class="muted">{{ pools.length }} 个</span>
        </div>
        <n-input v-model:value="poolKeyword" clearable size="small" placeholder="搜索池名称 / 编码" />
        <div class="pool-list-region">
          <n-spin :show="loadingPools" class="pool-list-spin">
            <n-empty v-if="filteredPools.length === 0" description="暂无股票池" />
            <button
              v-for="pool in filteredPools"
              :key="pool.pool_code"
              type="button"
              class="pool-row"
              :class="{ active: selectedPool?.pool_code === pool.pool_code }"
              @click="selectPool(pool.pool_code)"
            >
              <div class="pool-row-main">
                <strong>{{ pool.pool_name }}</strong>
                <span class="mono">{{ pool.pool_code }}</span>
              </div>
              <div class="pool-row-meta">
                <n-tag size="small" :bordered="false" :type="pool.is_enabled ? 'success' : 'warning'">
                  {{ pool.is_enabled ? '启用' : '停用' }}
                </n-tag>
                <strong>{{ pool.member_count }}</strong>
              </div>
            </button>
          </n-spin>
        </div>
      </aside>

      <section class="members-panel">
        <n-empty v-if="!selectedPool && !loadingPools" description="从左侧选择一个股票池" />
        <div v-else-if="selectedPool" class="members-content">
          <div class="pool-detail-head">
            <div class="pool-detail-main">
              <div class="title-line">
                <h2>{{ selectedPool.pool_name }}</h2>
                <n-tag size="small" :bordered="false" :type="selectedPool.is_enabled ? 'success' : 'warning'">
                  {{ selectedPool.is_enabled ? '启用' : '停用' }}
                </n-tag>
                <n-tag v-if="selectedPool.is_system" size="small" :bordered="false">系统池</n-tag>
                <n-tag v-if="selectedPool.is_dynamic" size="small" :bordered="false" type="info">动态范围</n-tag>
              </div>
              <span class="mono muted">{{ selectedPool.pool_code }}</span>
              <p v-if="selectedPool.description">{{ selectedPool.description }}</p>
              <p v-else-if="selectedPool.is_dynamic">成员随 <span class="mono">t_stock.status=active</span> 自动变化，不保存实体成员关系。</p>
            </div>
            <div class="pool-detail-actions">
              <n-switch :value="selectedPool.is_enabled" :loading="savingPool" @update:value="togglePoolEnabled" />
              <n-button v-if="!selectedPool.is_system" secondary @click="openEditPool">
                <template #icon><Pencil :size="16" /></template>
              </n-button>
              <n-button v-if="!selectedPool.is_system" secondary type="error" @click="confirmDeletePool">
                <template #icon><Trash2 :size="16" /></template>
              </n-button>
            </div>
          </div>

          <div class="members-toolbar">
            <n-input v-model:value="memberKeyword" clearable size="small" placeholder="搜索股票代码 / 名称" @keyup.enter="searchMembers" />
            <n-button quaternary circle title="搜索成员" @click="searchMembers">
              <template #icon><Search :size="16" /></template>
            </n-button>
            <n-button v-if="!selectedPool.is_dynamic" type="primary" secondary @click="openBatchAdd">
              <template #icon><Plus :size="16" /></template>
              添加股票
            </n-button>
          </div>

          <n-spin class="member-table-region" :show="loadingMembers">
            <n-data-table :columns="memberColumns" :data="members.items" :pagination="false" :max-height="tableMaxHeight" size="small" striped :row-key="memberRowKey" />
          </n-spin>

          <div class="members-footer">
            <span class="page-hint">显示 {{ memberRangeLabel }} / {{ members.total }}，每页 {{ pageSize }} 条</span>
            <n-pagination
              v-if="members.total > pageSize"
              v-model:page="memberPage"
              :page-size="pageSize"
              :item-count="members.total"
              size="small"
              @update:page="loadMembers"
            />
          </div>
        </div>
      </section>
    </div>

    <n-modal
      v-model:show="poolModalOpen"
      preset="card"
      :title="editingPool ? '编辑股票池' : '新建股票池'"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
    >
      <n-form label-placement="top">
        <n-form-item label="池编码">
          <n-input v-model:value="poolForm.pool_code" class="mono" :disabled="Boolean(editingPool)" placeholder="例如: my_watchlist" />
        </n-form-item>
        <n-form-item label="池名称">
          <n-input v-model:value="poolForm.pool_name" placeholder="例如: 新能源观察池" />
        </n-form-item>
        <n-form-item label="说明">
          <n-input v-model:value="poolForm.description" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="poolModalOpen = false">取消</n-button>
          <n-button type="primary" :loading="savingPool" @click="savePool">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="batchModalOpen" preset="card" title="添加股票" :style="{ width: 'min(620px, calc(100vw - 32px))' }">
      <div class="candidate-search-panel">
        <div class="candidate-search-input">
          <n-input
            v-model:value="candidateKeyword"
            clearable
            placeholder="搜索股票名称或代码"
            :loading="loadingCandidates"
            @keyup.enter="searchCandidates"
          >
            <template #prefix><Search :size="16" /></template>
          </n-input>
          <n-button quaternary circle title="搜索股票" :loading="loadingCandidates" @click="searchCandidates">
            <template #icon><Search :size="16" /></template>
          </n-button>
        </div>

        <div class="candidate-results">
          <n-spin :show="loadingCandidates">
            <n-empty v-if="!candidateKeyword.trim()" size="small" description="输入股票名称或代码后开始搜索" />
            <n-empty v-else-if="candidateResults.length === 0" size="small" description="未找到正常交易的股票" />
            <template v-else>
              <button
                v-for="candidate in candidateResults"
                :key="candidate.stock_code"
                type="button"
                class="candidate-row"
                :class="{ selected: isCandidateSelected(candidate.stock_code), disabled: candidate.is_member }"
                :disabled="candidate.is_member"
                @click="toggleCandidate(candidate)"
              >
                <span class="candidate-main">
                  <strong>{{ candidate.stock_name }}</strong>
                  <span class="mono">{{ candidate.stock_code }}</span>
                </span>
                <n-tag v-if="candidate.is_member" size="small" :bordered="false" type="default">已在池中</n-tag>
                <n-tag v-else-if="isCandidateSelected(candidate.stock_code)" size="small" :bordered="false" type="success">已选择</n-tag>
              </button>
            </template>
          </n-spin>
        </div>

        <section class="selected-candidates">
          <div class="selected-candidates-title">
            <strong>已选择</strong>
            <span class="page-hint">{{ selectedCandidates.length }} 只</span>
          </div>
          <n-empty v-if="selectedCandidates.length === 0" size="small" description="点击上方搜索结果添加" />
          <n-space v-else wrap>
            <n-tag
              v-for="candidate in selectedCandidates"
              :key="candidate.stock_code"
              closable
              type="success"
              @close="removeSelectedCandidate(candidate.stock_code)"
            >
              {{ candidate.stock_name }} {{ candidate.stock_code }}
            </n-tag>
          </n-space>
        </section>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button @click="closeBatchAdd">取消</n-button>
          <n-button type="primary" :disabled="selectedCandidates.length === 0" :loading="savingMembers" @click="saveSelectedMembers">添加</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="detailModalOpen" preset="card" title="股票详情" :style="{ width: 'min(720px, calc(100vw - 32px))' }">
      <n-spin :show="loadingDetail">
        <template v-if="memberDetail">
          <div class="stock-summary-grid">
            <div><span>股票代码</span><strong class="mono">{{ memberDetail.stock_code }}</strong></div>
            <div><span>股票名称</span><strong>{{ memberDetail.stock_name }}</strong></div>
            <div><span>交易所</span><strong>{{ memberDetail.exchange || '-' }}</strong></div>
            <div><span>所属行业</span><strong>{{ memberDetail.industry || '-' }}</strong></div>
            <div><span>地区</span><strong>{{ memberDetail.area || '-' }}</strong></div>
            <div><span>上市日期</span><strong>{{ memberDetail.list_date || '-' }}</strong></div>
          </div>
          <section class="sector-section">
            <h3>概念</h3>
            <n-empty v-if="memberDetail.concepts.length === 0" size="small" description="暂无已同步概念" />
            <n-space v-else wrap>
              <n-tag v-for="sector in memberDetail.concepts" :key="sector.sector_code" size="small" type="success">{{ sector.sector_name }}</n-tag>
            </n-space>
          </section>
          <section class="sector-section">
            <h3>行业</h3>
            <n-empty v-if="memberDetail.industries.length === 0" size="small" description="暂无已同步行业" />
            <n-space v-else wrap>
              <n-tag v-for="sector in memberDetail.industries" :key="sector.sector_code" size="small">{{ sector.sector_name }}</n-tag>
            </n-space>
          </section>
        </template>
      </n-spin>
      <template #footer>
        <n-space justify="end">
          <n-button @click="detailModalOpen = false">关闭</n-button>
          <n-button secondary :disabled="!memberDetail" @click="openMarketPlaceholder">
            <template #icon><ExternalLink :size="16" /></template>
            查看行情
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ExternalLink, Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-vue-next';
import {
  NButton,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPagination,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui';
import { stockPoolApi } from '@/api/stock-pool';
import type { StockPool, StockPoolCandidate, StockPoolMember, StockPoolMemberDetail, StockPoolMemberPage } from '@/types/stock-pool';
import { formatTime } from '@/utils/json';

const router = useRouter();
const message = useMessage();
const dialog = useDialog();
const pageSize = 20;
const loadingPools = ref(false);
const loadingMembers = ref(false);
const loadingDetail = ref(false);
const savingPool = ref(false);
const savingMembers = ref(false);
const poolKeyword = ref('');
const memberKeyword = ref('');
const pools = ref<StockPool[]>([]);
const selectedPoolCode = ref('');
const memberPage = ref(1);
const members = ref<StockPoolMemberPage>({ items: [], total: 0, page: 1, page_size: pageSize });
const poolModalOpen = ref(false);
const batchModalOpen = ref(false);
const detailModalOpen = ref(false);
const editingPool = ref<StockPool | null>(null);
const poolForm = ref({ pool_code: '', pool_name: '', description: '' });
const candidateKeyword = ref('');
const candidateResults = ref<StockPoolCandidate[]>([]);
const selectedCandidates = ref<StockPoolCandidate[]>([]);
const loadingCandidates = ref(false);
const memberDetail = ref<StockPoolMemberDetail | null>(null);
const tableMaxHeight = ref(440);
let candidateSearchTimer: ReturnType<typeof setTimeout> | undefined;

const selectedPool = computed(() => pools.value.find((pool) => pool.pool_code === selectedPoolCode.value) || null);
const filteredPools = computed(() => {
  const keyword = poolKeyword.value.trim().toLowerCase();
  if (!keyword) return pools.value;
  return pools.value.filter((pool) => [pool.pool_name, pool.pool_code].some((value) => value.toLowerCase().includes(keyword)));
});
const memberRangeLabel = computed(() => {
  if (members.value.total === 0) return '0';
  const start = (members.value.page - 1) * members.value.page_size + 1;
  return `${start}-${Math.min(start + members.value.items.length - 1, members.value.total)}`;
});

const memberColumns = computed<DataTableColumns<StockPoolMember>>(() => [
  { title: '代码', key: 'stock_code', width: 120, render: (row) => h('span', { class: 'mono' }, row.stock_code) },
  { title: '名称', key: 'stock_name', minWidth: 160, render: (row) => row.stock_name || '待基础资料同步' },
  { title: '加入时间', key: 'created_at', width: 180, render: (row) => formatTime(row.created_at) },
  {
    title: '操作', key: 'actions', width: selectedPool.value?.is_dynamic ? 80 : 150,
    render: (row) => h(NSpace, { size: 4 }, {
      default: () => [
        h(NButton, { size: 'tiny', secondary: true, onClick: () => openMemberDetail(row.stock_code) }, { default: () => '详情' }),
        ...(selectedPool.value?.is_dynamic
          ? []
          : [h(NButton, { size: 'tiny', tertiary: true, type: 'error', onClick: () => confirmRemoveMember(row.stock_code) }, { default: () => '移除' })]),
      ],
    }),
  },
]);

function memberRowKey(row: StockPoolMember) {
  return row.stock_code;
}

function updateTableHeight() {
  tableMaxHeight.value = Math.max(300, Math.min(720, window.innerHeight - 330));
}

async function loadPools() {
  loadingPools.value = true;
  try {
    pools.value = await stockPoolApi.list();
    const nextCode = pools.value.some((pool) => pool.pool_code === selectedPoolCode.value)
      ? selectedPoolCode.value
      : pools.value[0]?.pool_code || '';
    if (nextCode !== selectedPoolCode.value) selectedPoolCode.value = nextCode;
    if (nextCode) await loadMembers();
  } catch (error) {
    message.error(errorMessage(error, '加载股票池失败'));
  } finally {
    loadingPools.value = false;
  }
}

async function loadMembers() {
  if (!selectedPoolCode.value) return;
  loadingMembers.value = true;
  try {
    members.value = await stockPoolApi.members(selectedPoolCode.value, {
      keyword: memberKeyword.value.trim(),
      page: memberPage.value,
      pageSize,
    });
  } catch (error) {
    message.error(errorMessage(error, '加载池成员失败'));
  } finally {
    loadingMembers.value = false;
  }
}

function selectPool(poolCode: string) {
  if (poolCode === selectedPoolCode.value) return;
  selectedPoolCode.value = poolCode;
  memberPage.value = 1;
  void loadMembers();
}

function searchMembers() {
  memberPage.value = 1;
  void loadMembers();
}

function openCreatePool() {
  editingPool.value = null;
  poolForm.value = { pool_code: '', pool_name: '', description: '' };
  poolModalOpen.value = true;
}

function openEditPool() {
  if (!selectedPool.value || selectedPool.value.is_system) return;
  editingPool.value = selectedPool.value;
  poolForm.value = {
    pool_code: selectedPool.value.pool_code,
    pool_name: selectedPool.value.pool_name,
    description: selectedPool.value.description || '',
  };
  poolModalOpen.value = true;
}

async function savePool() {
  const payload = {
    pool_code: poolForm.value.pool_code.trim(),
    pool_name: poolForm.value.pool_name.trim(),
    description: poolForm.value.description.trim() || null,
  };
  if (!payload.pool_code || !payload.pool_name) {
    message.warning('请填写池编码和池名称');
    return;
  }
  savingPool.value = true;
  try {
    const saved = editingPool.value
      ? await stockPoolApi.update(editingPool.value.pool_code, { pool_name: payload.pool_name, description: payload.description })
      : await stockPoolApi.create(payload);
    selectedPoolCode.value = saved.pool_code;
    poolModalOpen.value = false;
    await loadPools();
    message.success(editingPool.value ? '股票池已更新' : '股票池已创建');
  } catch (error) {
    message.error(errorMessage(error, '保存股票池失败'));
  } finally {
    savingPool.value = false;
  }
}

async function togglePoolEnabled(value: boolean) {
  if (!selectedPool.value) return;
  savingPool.value = true;
  try {
    await stockPoolApi.update(selectedPool.value.pool_code, { is_enabled: value });
    await loadPools();
  } catch (error) {
    message.error(errorMessage(error, '更新股票池状态失败'));
  } finally {
    savingPool.value = false;
  }
}

function confirmDeletePool() {
  if (!selectedPool.value || selectedPool.value.is_system) return;
  const pool = selectedPool.value;
  dialog.error({
    title: '删除股票池',
    content: `将删除 ${pool.pool_name} 及其中全部成员关系，此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await stockPoolApi.remove(pool.pool_code);
        selectedPoolCode.value = '';
        await loadPools();
        message.success('股票池已删除');
      } catch (error) {
        message.error(errorMessage(error, '删除股票池失败'));
      }
    },
  });
}

function openBatchAdd() {
  candidateKeyword.value = '';
  candidateResults.value = [];
  selectedCandidates.value = [];
  batchModalOpen.value = true;
}

function closeBatchAdd() {
  batchModalOpen.value = false;
  candidateKeyword.value = '';
  candidateResults.value = [];
  selectedCandidates.value = [];
}

async function searchCandidates() {
  if (!selectedPool.value) return;
  const keyword = candidateKeyword.value.trim();
  if (!keyword) {
    candidateResults.value = [];
    return;
  }
  loadingCandidates.value = true;
  try {
    const results = await stockPoolApi.candidateStocks(selectedPool.value.pool_code, keyword);
    if (candidateKeyword.value.trim() === keyword) candidateResults.value = results;
  } catch (error) {
    message.error(errorMessage(error, '搜索股票失败'));
  } finally {
    loadingCandidates.value = false;
  }
}

function isCandidateSelected(stockCode: string) {
  return selectedCandidates.value.some((candidate) => candidate.stock_code === stockCode);
}

function toggleCandidate(candidate: StockPoolCandidate) {
  if (candidate.is_member) return;
  if (isCandidateSelected(candidate.stock_code)) {
    removeSelectedCandidate(candidate.stock_code);
    return;
  }
  selectedCandidates.value = [...selectedCandidates.value, candidate];
}

function removeSelectedCandidate(stockCode: string) {
  selectedCandidates.value = selectedCandidates.value.filter((candidate) => candidate.stock_code !== stockCode);
}

async function saveSelectedMembers() {
  if (!selectedPool.value || selectedCandidates.value.length === 0) {
    message.warning('请先选择至少一只股票');
    return;
  }
  savingMembers.value = true;
  try {
    const result = await stockPoolApi.addMembers(selectedPool.value.pool_code, selectedCandidates.value.map((candidate) => candidate.stock_code));
    closeBatchAdd();
    memberPage.value = 1;
    await Promise.all([loadPools(), loadMembers()]);
    message.success(result.added_count ? `已添加 ${result.added_count} 只股票` : '股票已在当前池中');
  } catch (error) {
    message.error(errorMessage(error, '添加股票失败'));
  } finally {
    savingMembers.value = false;
  }
}

function confirmRemoveMember(stockCode: string) {
  if (!selectedPool.value) return;
  dialog.warning({
    title: '移除股票',
    content: `将从 ${selectedPool.value.pool_name} 移除 ${stockCode}。`,
    positiveText: '移除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await stockPoolApi.removeMember(selectedPool.value!.pool_code, stockCode);
        await Promise.all([loadPools(), loadMembers()]);
        message.success('股票已移除');
      } catch (error) {
        message.error(errorMessage(error, '移除股票失败'));
      }
    },
  });
}

async function openMemberDetail(stockCode: string) {
  if (!selectedPool.value) return;
  detailModalOpen.value = true;
  loadingDetail.value = true;
  memberDetail.value = null;
  try {
    memberDetail.value = await stockPoolApi.memberDetail(selectedPool.value.pool_code, stockCode);
  } catch (error) {
    message.error(errorMessage(error, '加载股票详情失败'));
  } finally {
    loadingDetail.value = false;
  }
}

function openMarketPlaceholder() {
  if (!memberDetail.value) return;
  detailModalOpen.value = false;
  void router.push({ path: '/market', query: { stock_code: memberDetail.value.stock_code } });
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

watch(memberKeyword, () => {
  memberPage.value = 1;
});

watch(candidateKeyword, () => {
  if (candidateSearchTimer) clearTimeout(candidateSearchTimer);
  if (!candidateKeyword.value.trim()) {
    candidateResults.value = [];
    return;
  }
  candidateSearchTimer = setTimeout(() => void searchCandidates(), 250);
});

onMounted(() => {
  updateTableHeight();
  window.addEventListener('resize', updateTableHeight);
  void loadPools();
});
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateTableHeight);
  if (candidateSearchTimer) clearTimeout(candidateSearchTimer);
});
</script>

<style scoped>
.stock-pool-page { padding: 22px 24px 24px; }
.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
.topbar h1 { margin: 0; font-size: 24px; }
.topbar p { margin: 6px 0 0; color: #667085; }
.pool-workspace { height: max(560px, calc(100vh - 148px)); display: grid; grid-template-columns: minmax(288px, 320px) minmax(0, 1fr); overflow: hidden; border: 1px solid #d8e0e5; background: #fff; }
.pool-list-panel, .members-panel { height: 100%; min-width: 0; padding: 16px; box-sizing: border-box; }
.pool-list-panel { min-height: 0; display: flex; flex-direction: column; gap: 10px; border-right: 1px solid #d8e0e5; }
.panel-heading { display: flex; justify-content: space-between; color: #344054; font-size: 13px; font-weight: 700; }
.pool-list-region { min-height: 0; flex: 1; overflow-x: hidden; overflow-y: scroll; overscroll-behavior: contain; scrollbar-gutter: stable; }
.pool-list-spin, .pool-list-spin :deep(.n-spin-container) { height: auto; min-height: 100%; }
.pool-row { width: 100%; min-height: 62px; padding: 9px 6px; display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 0; border-bottom: 1px solid #edf1f3; background: transparent; color: #1f2933; text-align: left; cursor: pointer; }
.pool-row:hover, .pool-row.active { background: #e8f5f0; }
.pool-row.active { box-shadow: inset 3px 0 0 #1f8a70; }
.pool-row-main { min-width: 0; display: grid; gap: 4px; }
.pool-row-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pool-row-main span { overflow: hidden; color: #667085; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.pool-row-meta { display: grid; justify-items: end; gap: 4px; color: #667085; font-size: 12px; }
.members-panel { min-height: 0; overflow: hidden; }
.members-content { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
.pool-detail-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 2px 0 12px; border-bottom: 1px solid #d8e0e5; }
.pool-detail-main { min-width: 0; }
.title-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.title-line h2 { margin: 0; font-size: 20px; }
.pool-detail-main p { margin: 6px 0 0; color: #667085; font-size: 13px; }
.pool-detail-actions { display: flex; align-items: center; gap: 8px; }
.members-toolbar { display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid #e4e7ec; background: #f8fafc; }
.members-toolbar :deep(.n-input) { min-width: 0; flex: 1; }
.member-table-region { min-height: 0; flex: 1; overflow: hidden; border: 1px solid #d8e0e5; }
.member-table-region :deep(.n-spin-container) { height: 100%; min-height: 0; overflow: auto; }
.members-footer { min-height: 34px; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.page-hint { color: #98a2b3; font-size: 12px; }
.candidate-search-panel { display: grid; gap: 14px; }
.candidate-search-input { display: flex; align-items: center; gap: 8px; }
.candidate-search-input :deep(.n-input) { flex: 1; }
.candidate-results { min-height: 230px; max-height: 300px; overflow-y: auto; border: 1px solid #e4e7ec; }
.candidate-results :deep(.n-spin-container) { min-height: 228px; }
.candidate-row { width: 100%; min-height: 50px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 12px; border: 0; border-bottom: 1px solid #edf1f3; background: #fff; color: #1f2933; text-align: left; cursor: pointer; }
.candidate-row:last-child { border-bottom: 0; }
.candidate-row:hover, .candidate-row.selected { background: #e8f5f0; }
.candidate-row.selected { box-shadow: inset 3px 0 0 #1f8a70; }
.candidate-row.disabled { cursor: not-allowed; opacity: 0.64; }
.candidate-main { display: grid; gap: 3px; min-width: 0; }
.candidate-main strong, .candidate-main span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.candidate-main span { color: #667085; font-size: 12px; }
.selected-candidates { min-height: 92px; padding: 12px; border: 1px solid #e4e7ec; background: #f8fafc; }
.selected-candidates-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; font-size: 13px; }
.stock-summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid #e4e7ec; }
.stock-summary-grid div { min-width: 0; padding: 10px 12px; border-right: 1px solid #e4e7ec; border-bottom: 1px solid #e4e7ec; }
.stock-summary-grid div:nth-child(2n) { border-right: 0; }
.stock-summary-grid div:nth-last-child(-n + 2) { border-bottom: 0; }
.stock-summary-grid span, .stock-summary-grid strong { display: block; }
.stock-summary-grid span { margin-bottom: 4px; color: #667085; font-size: 12px; }
.stock-summary-grid strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.sector-section { margin-top: 18px; }
.sector-section h3 { margin: 0 0 8px; font-size: 14px; }
@media (max-width: 900px) {
  .stock-pool-page { padding: 14px; }
  .topbar { align-items: center; }
  .topbar h1 { font-size: 22px; }
  .topbar p { max-width: 260px; font-size: 13px; line-height: 1.5; }
  .pool-workspace { height: auto; min-height: 0; grid-template-columns: 1fr; overflow: visible; }
  .pool-list-panel { height: 314px; border-right: 0; border-bottom: 1px solid #d8e0e5; }
  .members-panel { min-height: 580px; }
  .members-content { height: 580px; }
  .members-footer { align-items: flex-start; flex-direction: column; }
}

@media (max-width: 560px) {
  .stock-pool-page { padding: 12px; }
  .topbar { align-items: flex-start; }
  .topbar > :last-child { flex-shrink: 0; }
  .topbar :deep(.n-button) { padding-inline: 10px; }
  .pool-list-panel, .members-panel { padding: 12px; }
  .pool-list-panel { height: 300px; }
  .pool-detail-head { gap: 10px; }
  .title-line h2 { font-size: 18px; }
  .pool-detail-main p { font-size: 12px; }
  .members-toolbar { flex-wrap: wrap; }
  .members-toolbar :deep(.n-input) { flex-basis: calc(100% - 42px); }
  .members-toolbar > :last-child { margin-left: auto; }
  .member-table-region :deep(.n-data-table-table) { min-width: 560px; }
  .members-footer { gap: 8px; }
  .stock-summary-grid { grid-template-columns: 1fr; }
  .stock-summary-grid div, .stock-summary-grid div:nth-child(2n) { border-right: 0; }
  .stock-summary-grid div:nth-last-child(-n + 2) { border-bottom: 1px solid #e4e7ec; }
  .stock-summary-grid div:last-child { border-bottom: 0; }
}
</style>
