<template>
  <main class="workspace strategy-center-page">
    <header class="topbar">
      <div>
        <div class="eyebrow">研究 / 模拟交易基础层</div>
        <h1>策略中心</h1>
        <p>策略定义、收盘候选、次日确认与模拟交易将使用同一审计链路。当前只开放研究配置，不会发出买卖指令或伪造回测结果。</p>
      </div>
      <div class="header-actions"><n-button secondary :loading="loading" @click="load"><template #icon><RefreshCw :size="16" /></template>刷新</n-button><n-button type="primary" @click="openCreate"><template #icon><Plus :size="16" /></template>新建策略草稿</n-button></div>
    </header>

    <n-alert type="info" :show-icon="true" class="page-alert">
      {{ dashboard?.execution_readiness_reason || '正在读取策略执行状态。' }} “未触发买点”只记录为候选结果，不会计入模拟交易的盈亏或胜率。
    </n-alert>

    <n-spin :show="loading">
      <section class="summary-grid">
        <article><span>策略定义</span><strong>{{ dashboard?.definitions.length || 0 }}</strong><small>草稿与研究策略</small></article>
        <article><span>等待次日确认</span><strong>{{ candidateCount('pending_confirmation') + candidateCount('watching') }}</strong><small>尚未产生模拟成交</small></article>
        <article><span>未触发买点</span><strong>{{ candidateCount('not_triggered') }}</strong><small>不计为策略失败</small></article>
        <article><span>模拟持仓</span><strong>{{ tradeCount('open') }}</strong><small>触发后才会进入</small></article>
        <article><span>最近候选日</span><strong>{{ dashboard?.latest_signal_trade_date || '-' }}</strong><small>当前尚未接入 evaluator</small></article>
      </section>

      <section class="strategy-layout">
        <section class="surface strategy-list-surface">
          <div class="panel-heading"><div><span class="panel-kicker">策略定义</span><h2>研究队列</h2></div><span class="muted">每个策略独立拥有动态股票池</span></div>
          <div v-if="dashboard?.definitions.length" class="strategy-list">
            <button v-for="item in dashboard.definitions" :key="item.strategy_code" class="strategy-card" :class="{ selected: selected?.strategy_code === item.strategy_code }" @click="select(item)">
              <div class="strategy-card-head"><div><strong>{{ item.strategy_name }}</strong><small>{{ item.strategy_code }}</small></div><n-tag size="small" :type="statusType(item.status)" :bordered="false">{{ statusLabel(item.status) }}</n-tag></div>
              <p>{{ item.description || '尚未填写策略研究说明。' }}</p>
              <div class="strategy-meta"><span>{{ entryModeLabel(item.entry_mode) }}</span><span>最多 {{ item.max_holding_trade_days }} 个交易日</span><span>{{ item.pool_name || '策略池待创建' }}</span></div>
              <div class="strategy-counts"><span>候选 {{ item.candidate_summary.total_count || 0 }}</span><span>未触发 {{ item.candidate_summary.not_triggered_count || 0 }}</span><span>模拟成交 {{ item.trade_summary.total_count || 0 }}</span></div>
            </button>
          </div>
          <n-empty v-else description="尚未创建策略草稿" />
        </section>

        <section class="surface editor-surface">
          <template v-if="selected">
            <div class="panel-heading"><div><span class="panel-kicker">策略配置</span><h2>{{ selected.strategy_name }}</h2></div><n-tag :type="statusType(selected.status)" :bordered="false">{{ statusLabel(selected.status) }}</n-tag></div>
            <div class="settings-grid"><label>策略名称<n-input v-model:value="editForm.strategy_name" /></label><label>确认时点<n-select v-model:value="editForm.entry_mode" :options="entryModeOptions" /></label><label>最长持有（交易日）<n-input-number v-model:value="editForm.max_holding_trade_days" :min="1" :max="20" /></label><label>研究状态<n-select v-model:value="editForm.status" :options="statusOptions" /></label></div>
            <label class="description-label">研究说明<n-input v-model:value="editForm.description" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="记录策略想解决的行情、候选条件和排除条件；规则 evaluator 上线后再配置可执行表达式。" /></label>
            <div class="pool-boundary"><b>专属动态股票池</b><span>{{ selected.pool_name || '-' }}（{{ selected.pool_code || '-' }}）</span><small>以后只显示仍等待确认的策略候选；成交后转由持仓池监控，过期或未触发的候选会自然退出。</small></div>
            <div class="editor-actions"><n-button :loading="saving" @click="save">保存研究配置</n-button></div>
          </template>
          <n-empty v-else description="选择左侧策略后查看研究配置" />
        </section>
      </section>

      <section class="surface candidates-surface">
        <div class="panel-heading"><div><span class="panel-kicker">候选与执行链路</span><h2>策略候选</h2></div><span class="muted">候选由后续收盘 evaluator 写入；本页不会直接生成信号</span></div>
        <div class="candidate-filters"><n-select v-model:value="candidateStrategyCode" clearable :options="strategyOptions" placeholder="全部策略" /><n-input v-model:value="candidateTradeDate" clearable placeholder="报告日 YYYY-MM-DD" @keyup.enter="loadCandidates" /><n-button secondary :loading="loadingCandidates" @click="loadCandidates">查询</n-button></div>
        <div v-if="candidates.length" class="candidate-table"><div class="candidate-row candidate-head"><span>候选日 / 策略</span><span>股票</span><span>评分</span><span>确认状态</span><span>模拟交易</span></div><div v-for="item in candidates" :key="item.id" class="candidate-row"><span><b>{{ item.signal_trade_date }}</b><small>{{ item.strategy_name }}</small></span><span><b>{{ item.stock_name || item.stock_code }}</b><small>{{ item.stock_code }}</small></span><span>{{ formatNumber(item.score) }}<small>{{ item.rank_no ? `第 ${item.rank_no} 名` : '-' }}</small></span><span><n-tag size="small" :type="candidateStatusType(item.candidate_status)" :bordered="false">{{ candidateStatusLabel(item.candidate_status) }}</n-tag><small>{{ item.confirmation_deadline || '确认日期待 evaluator 写入' }}</small></span><span><template v-if="item.paper_trade"><b>{{ paperTradeLabel(item.paper_trade.trade_status) }}</b><small>{{ item.paper_trade.realized_pnl_pct == null ? `买入 ${item.paper_trade.entry_price}` : `收益 ${formatPercent(item.paper_trade.realized_pnl_pct)}` }}</small></template><small v-else>未成交</small></span></div></div>
        <n-empty v-else description="暂无策略候选。创建研究配置不会自动产生候选；需要等待后续策略 evaluator 对收盘事实进行扫描。" />
      </section>
    </n-spin>

    <n-modal v-model:show="createOpen" preset="card" title="新建短线策略研究草稿" style="width: min(620px, calc(100vw - 28px))">
      <n-form label-placement="top"><n-form-item label="策略代码"><n-input v-model:value="createForm.strategy_code" placeholder="例如 first_board_theme_relay" /></n-form-item><n-form-item label="策略名称"><n-input v-model:value="createForm.strategy_name" placeholder="例如 首板主线接力（研究）" /></n-form-item><n-form-item label="候选确认时点"><n-select v-model:value="createForm.entry_mode" :options="entryModeOptions" /></n-form-item><n-form-item label="最长持有交易日"><n-input-number v-model:value="createForm.max_holding_trade_days" :min="1" :max="20" /></n-form-item><n-form-item label="研究说明"><n-input v-model:value="createForm.description" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" /></n-form-item></n-form>
      <template #footer><div class="modal-actions"><n-button @click="createOpen = false">取消</n-button><n-button type="primary" :loading="creating" @click="create">创建草稿</n-button></div></template>
    </n-modal>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { NAlert, NButton, NEmpty, NForm, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpin, NTag, useMessage } from 'naive-ui';
import { Plus, RefreshCw } from 'lucide-vue-next';
import { strategyCenterApi } from '@/api/strategy-center';
import type { StrategyCandidate, StrategyDashboard, StrategyDefinition, StrategyEntryMode, StrategyStatus } from '@/types/strategy-center';

const message = useMessage();
const dashboard = ref<StrategyDashboard | null>(null);
const selected = ref<StrategyDefinition | null>(null);
const candidates = ref<StrategyCandidate[]>([]);
const loading = ref(false); const loadingCandidates = ref(false); const creating = ref(false); const saving = ref(false); const createOpen = ref(false);
const candidateStrategyCode = ref<string | null>(null); const candidateTradeDate = ref('');
const entryModeOptions = [{ label: '集合竞价确认', value: 'auction' }, { label: '开盘确认', value: 'open' }, { label: '盘中确认', value: 'intraday' }];
const statusOptions = [{ label: '草稿', value: 'draft' }, { label: '研究中', value: 'research' }, { label: '归档', value: 'archived' }];
const createForm = reactive({ strategy_code: '', strategy_name: '', description: '', entry_mode: 'auction' as StrategyEntryMode, max_holding_trade_days: 3 });
const editForm = reactive({ strategy_name: '', description: '', entry_mode: 'auction' as StrategyEntryMode, max_holding_trade_days: 3, status: 'draft' as StrategyStatus });
const strategyOptions = computed(() => (dashboard.value?.definitions || []).map((item) => ({ label: `${item.strategy_name} (${item.strategy_code})`, value: item.strategy_code })));

function candidateCount(status: string) { return dashboard.value?.candidate_counts?.[status] || 0; }
function tradeCount(status: string) { return dashboard.value?.paper_trade_counts?.[status] || 0; }
function entryModeLabel(value: string) { return ({ auction: '集合竞价确认', open: '开盘确认', intraday: '盘中确认' } as Record<string, string>)[value] || value; }
function statusLabel(value: string) { return ({ draft: '草稿', research: '研究中', enabled: '待执行器', archived: '已归档' } as Record<string, string>)[value] || value; }
function statusType(value: string) { return ({ draft: 'default', research: 'warning', enabled: 'success', archived: 'default' } as Record<string, 'default' | 'warning' | 'success'>)[value] || 'default'; }
function candidateStatusLabel(value: string) { return ({ pending_confirmation: '待次日确认', watching: '监控中', entry_triggered: '已触发买点', not_triggered: '未触发买点', expired: '已过期', cancelled: '已取消' } as Record<string, string>)[value] || value; }
function candidateStatusType(value: string) { return ({ pending_confirmation: 'warning', watching: 'info', entry_triggered: 'success', not_triggered: 'default', expired: 'default', cancelled: 'error' } as Record<string, 'default' | 'warning' | 'info' | 'success' | 'error'>)[value] || 'default'; }
function paperTradeLabel(value: string) { return ({ open: '模拟持有', closed: '已结束', void: '已作废' } as Record<string, string>)[value] || value; }
function formatNumber(value: number | null) { return typeof value === 'number' ? value.toFixed(1) : '-'; }
function formatPercent(value: number | null) { return typeof value === 'number' ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}%` : '-'; }
function select(item: StrategyDefinition) { selected.value = item; editForm.strategy_name = item.strategy_name; editForm.description = item.description || ''; editForm.entry_mode = item.entry_mode; editForm.max_holding_trade_days = item.max_holding_trade_days; editForm.status = item.status; candidateStrategyCode.value = item.strategy_code; void loadCandidates(); }
async function load() { loading.value = true; try { dashboard.value = await strategyCenterApi.dashboard(); const refreshed = selected.value && dashboard.value.definitions.find((item) => item.strategy_code === selected.value?.strategy_code); if (refreshed) select(refreshed); else if (!selected.value && dashboard.value.definitions[0]) select(dashboard.value.definitions[0]); } catch (error) { message.error(error instanceof Error ? error.message : '读取策略中心失败'); } finally { loading.value = false; } }
async function loadCandidates() { loadingCandidates.value = true; try { candidates.value = await strategyCenterApi.candidates({ strategy_code: candidateStrategyCode.value || undefined, signal_trade_date: candidateTradeDate.value.trim() || undefined, limit: 200 }); } catch (error) { message.error(error instanceof Error ? error.message : '读取策略候选失败'); } finally { loadingCandidates.value = false; } }
function openCreate() { createForm.strategy_code = ''; createForm.strategy_name = ''; createForm.description = ''; createForm.entry_mode = 'auction'; createForm.max_holding_trade_days = 3; createOpen.value = true; }
async function create() { if (!createForm.strategy_code || !createForm.strategy_name) { message.warning('请填写策略代码和名称'); return; } creating.value = true; try { const created = await strategyCenterApi.create({ ...createForm, description: createForm.description || null }); createOpen.value = false; await load(); const item = dashboard.value?.definitions.find((row) => row.strategy_code === created.strategy_code); if (item) select(item); message.success('策略草稿和专属动态股票池已创建'); } catch (error) { message.error(error instanceof Error ? error.message : '创建策略草稿失败'); } finally { creating.value = false; } }
async function save() { if (!selected.value) return; saving.value = true; try { await strategyCenterApi.update(selected.value.strategy_code, { ...editForm, description: editForm.description || null }); await load(); message.success('研究配置已保存'); } catch (error) { message.error(error instanceof Error ? error.message : '保存策略失败'); } finally { saving.value = false; } }
onMounted(() => { void load(); void loadCandidates(); });
</script>

<style scoped>
.strategy-center-page{padding:22px 24px 34px;color:#17212b}.topbar{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:14px}.eyebrow,.panel-kicker{color:#9a6700;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.topbar h1{margin:4px 0 0;font-size:26px}.topbar p{max-width:840px;margin:8px 0 0;color:#667085;line-height:1.6}.header-actions,.editor-actions,.modal-actions{display:flex;gap:8px;align-items:center}.page-alert{margin-bottom:14px}.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.summary-grid article,.surface{border:1px solid #dce5e9;border-radius:8px;background:#fff;box-shadow:0 1px 2px rgba(16,24,40,.03)}.summary-grid article{display:grid;gap:6px;min-height:100px;padding:13px}.summary-grid span,.summary-grid small{color:#667085;font-size:12px}.summary-grid strong{font-size:22px;font-variant-numeric:tabular-nums}.strategy-layout{display:grid;grid-template-columns:minmax(360px,.9fr) minmax(420px,1.1fr);gap:14px;margin-top:14px}.surface{padding:15px}.panel-heading{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:12px}.panel-heading h2{margin:3px 0 0;font-size:18px}.muted{color:#667085;font-size:12px;line-height:1.5}.strategy-list{display:grid;gap:9px}.strategy-card{width:100%;display:grid;gap:9px;padding:12px;border:1px solid #e4e9ef;border-radius:7px;background:#fff;color:#17212b;text-align:left;cursor:pointer}.strategy-card:hover,.strategy-card.selected{border-color:#3182ce;background:#f7fbff}.strategy-card-head{display:flex;justify-content:space-between;gap:10px}.strategy-card-head>div{display:grid;gap:2px}.strategy-card-head strong{font-size:14px}.strategy-card-head small,.strategy-card p,.strategy-meta,.strategy-counts{color:#667085;font-size:11px}.strategy-card p{margin:0;line-height:1.5}.strategy-meta,.strategy-counts{display:flex;flex-wrap:wrap;gap:5px}.strategy-meta span,.strategy-counts span{padding:3px 5px;border-radius:4px;background:#f2f4f7}.settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.settings-grid>label,.description-label{display:grid;gap:5px;color:#475467;font-size:12px}.description-label{margin-top:12px}.pool-boundary{display:grid;gap:4px;margin-top:12px;padding:10px;border:1px solid #f0dfb4;border-radius:6px;background:#fffcf5;font-size:12px}.pool-boundary b{color:#9a6700}.pool-boundary span,.pool-boundary small{color:#667085}.editor-actions{justify-content:flex-end;margin-top:14px}.candidates-surface{margin-top:14px}.candidate-filters{display:flex;gap:8px;max-width:620px;margin-bottom:12px}.candidate-filters :deep(.n-select),.candidate-filters :deep(.n-input){flex:1}.candidate-table{border:1px solid #e4e9ef;border-radius:7px;overflow:auto}.candidate-row{display:grid;grid-template-columns:1.35fr 1fr .55fr 1.1fr 1fr;gap:10px;align-items:center;min-width:720px;padding:10px 12px;border-top:1px solid #edf1f3;font-size:12px}.candidate-row:first-child{border-top:0}.candidate-row>span{display:grid;gap:3px;min-width:0}.candidate-row b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.candidate-row small{color:#667085;font-size:11px}.candidate-head{color:#667085;background:#f8fafc;font-size:11px;font-weight:700}.candidate-head span{display:block}@media(max-width:1100px){.summary-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.strategy-layout{grid-template-columns:1fr}.settings-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}@media(max-width:700px){.strategy-center-page{padding:14px}.topbar{flex-direction:column}.summary-grid,.settings-grid{grid-template-columns:1fr}.candidate-filters{flex-direction:column}.header-actions{width:100%;justify-content:flex-end}}
</style>
