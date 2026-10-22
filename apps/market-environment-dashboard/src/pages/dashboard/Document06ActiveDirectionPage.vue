<script setup lang="ts">
import { Target } from 'lucide-vue-next'
import { computed, ref } from 'vue'

import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'
import type { ActiveResearchRow } from '../../types'

const market = useMarketStore()
const ctx = useDocumentContext()
const view = ref<'overview' | 'turnover' | 'core' | 'patterns' | 'fundamentals'>('overview')
const selectedSecurityId = ref<string | null>(null)
const activeDirection = computed(() => market.chapter?.activeDirection)
const workbench = computed(() => market.chapter?.activeDirectionWorkbench)
const researchRows = computed<ActiveResearchRow[]>(() => {
  const rows = workbench.value?.turnoverMap?.rows
  return rows?.length ? rows : ((activeDirection.value?.researchRows ?? activeDirection.value?.topStocks ?? []) as ActiveResearchRow[])
})
const selectedRow = computed(() => researchRows.value.find((row) => String((row as any).securityId ?? row.code) === selectedSecurityId.value) ?? researchRows.value[0] ?? null)
const derivedQuality = computed(() => activeDirection.value?.quality?.derived ? activeDirection.value.quality : workbench.value?.lineage as any)
const views = [
  ['overview', '方向总览'], ['turnover', 'Top-30 资金地图'], ['core', '核心股六项辨识'],
  ['patterns', '异动资金 / 放量长上影 / 一进二'], ['fundamentals', '基本面与次日验证'],
] as const
function formatAmount(value: number | null | undefined): string { return value == null ? '--' : Math.abs(value) >= 100000000 ? `${(value / 100000000).toFixed(1)} 亿` : `${(value / 10000).toFixed(0)} 万` }
function formatPct(value: number | null | undefined): string { return value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%` }
function formatPosition(value: number | null | undefined): string { return value == null ? '--' : `${(value * 100).toFixed(0)}%` }
function changeTone(value: number | null | undefined): 'positive' | 'negative' | 'flat' { return value == null ? 'flat' : value > 0 ? 'positive' : value < 0 ? 'negative' : 'flat' }
function selectRow(row: ActiveResearchRow) { selectedSecurityId.value = String((row as any).securityId ?? row.code ?? '') }
</script>

<template>
  <p class="page-flow-label">方向发现 → 容量验证 → 核心辨识 → 模式观察 → 风险过滤 → 次日验证</p>
  <section class="panel workbench-header"><div class="panel-heading"><div><span class="panel-kicker">大成交额主动进攻方向</span><h2>{{ activeDirection?.state || workbench?.state || '主动进攻方向研究工作台' }}</h2></div><span class="quality-badge" :class="ctx.qualityTone(activeDirection?.quality)">{{ ctx.qualityLabel(activeDirection?.quality) }}</span></div><p class="workbench-meta">精确日期 {{ market.data?.asOf || workbench?.asOf || '--' }} · revision {{ market.snapshotRevision || '未提供' }} · 规则状态 documented-only / needs-backtest</p><p v-if="activeDirection?.summary" class="panel-summary">{{ activeDirection.summary }}</p><p v-if="derivedQuality" class="panel-quality-note">来源 {{ derivedQuality.source || '--' }} · {{ derivedQuality.rankingMethod || '本地派生排序' }}<span v-if="derivedQuality.industryMappingCoverage != null"> · 行业映射覆盖 {{ (derivedQuality.industryMappingCoverage * 100).toFixed(0) }}%</span></p></section>
  <nav class="workbench-tabs" aria-label="主动进攻方向研究视图"><button v-for="item in views" :key="item[0]" type="button" :aria-pressed="view === item[0]" :class="{ active: view === item[0] }" @click="view = item[0]">{{ item[1] }}</button></nav>

  <section v-if="view === 'overview'" class="panel evidence-panel"><h3>方向总览</h3><p>观察标签与规范方向身份分离；未完成日期有效映射时不晋级方向候选。</p><div class="evidence-grid"><div v-for="item in (workbench?.directionOverview?.observations as any[] || [])" :key="item.label" class="evidence-card"><strong>{{ item.label }}</strong><span>{{ item.count }} 只 · observation</span></div><div v-if="!(workbench?.directionOverview?.observations as any[] || []).length && !activeDirection?.topStocks?.length" class="empty-evidence compact"><Target :size="24" /><strong>未确认容量进攻方向</strong><p>{{ activeDirection?.quality.warning || '成交额前 30、方向聚集度和板块同步率尚未形成完整证据。' }}</p></div></div><div v-if="!workbench && activeDirection?.topStocks?.length" class="table-scroll legacy-table"><table><thead><tr><th>个股</th><th>涨跌幅</th><th>成交额</th><th>方向</th><th>收盘位置</th></tr></thead><tbody><tr v-for="stock in activeDirection.topStocks" :key="stock.code || stock.name"><td><strong>{{ stock.name || '--' }}</strong><span>{{ stock.code || '--' }}</span></td><td :class="changeTone(stock.changePct)">{{ formatPct(stock.changePct) }}</td><td>{{ formatAmount(stock.amount) }}</td><td>{{ stock.industry || '--' }}</td><td>{{ formatPosition(stock.closePosition) }}</td></tr></tbody></table></div><p class="rule-note">QTS-04-01 · score=null · canonical candidate {{ (workbench?.directionOverview?.canonicalCandidates as any[] || []).length ? '可观察' : '不可确认' }}</p></section>

  <section v-else-if="view === 'turnover'" class="panel table-panel"><h3>Top-30 成交额资金地图</h3><div class="table-scroll"><table><thead><tr><th>排名 / 个股</th><th>涨跌幅</th><th>成交额</th><th>方向观察</th><th>收盘位置</th><th>历史</th></tr></thead><tbody><tr v-for="row in researchRows" :key="row.code || row.name" :class="{ selected: String((row as any).securityId ?? row.code) === selectedSecurityId }" tabindex="0" @click="selectRow(row)" @keydown.enter="selectRow(row)"><td><strong>#{{ row.rank || '--' }}</strong> {{ row.name || '--' }}<span>{{ row.code || '--' }}</span></td><td :class="changeTone(row.changePct)">{{ formatPct(row.changePct) }}</td><td>{{ formatAmount(row.amount) }}</td><td>{{ row.rawDirectionLabel || row.industry || '--' }}</td><td>{{ formatPosition(row.closePosition) }}</td><td>{{ (row as any).historyQuality === 'missing' ? 'missing' : ((row as any).priorRank ?? '--') }}</td></tr></tbody></table></div><p class="rule-note">来源/排序与行业映射保留在质量 lineage；旧快照只有 Top-10 时，历史分母保持 null。</p></section>

  <section v-else-if="view === 'core'" class="panel evidence-panel"><h3>核心股六项辨识</h3><p>当前选中：{{ selectedRow?.name || '--' }}（{{ selectedRow?.code || '--' }}）</p><div class="evidence-grid"><div v-for="trace in ((workbench?.securityEvidence?.[String(selectedRow?.code)] as any)?.traces || [])" :key="trace.ruleId" class="evidence-card"><strong>{{ trace.ruleId }}</strong><span>{{ trace.state }} · documented-only</span></div></div><p class="rule-note">不自动赋予龙头、中军、补涨角色；score=null，calibrationState=needs-backtest。</p></section>
  <section v-else-if="view === 'patterns'" class="panel evidence-panel"><h3>候选模式观察池</h3><div class="evidence-grid"><div class="evidence-card"><strong>异动资金</strong><span>insufficient · QTS-04-04</span></div><div class="evidence-card"><strong>放量长上影</strong><span>insufficient · QTS-04-05</span></div><div class="evidence-card"><strong>一进二</strong><span>{{ (workbench?.candidatePools?.firstToSecond as any)?.state || 'missing' }} · strict first-to-second / five-session 分开 · QTS-04-06</span></div></div><div class="evidence-grid"><div class="evidence-card"><strong>集合竞价</strong><span>{{ (workbench?.candidatePools?.firstToSecond as any)?.auction?.state || 'pending' }} · {{ ((workbench?.candidatePools?.firstToSecond as any)?.auction?.missingInputs || []).join('、') || '待恢复' }}</span></div><div class="evidence-card"><strong>盘中封板事实</strong><span>{{ (workbench?.candidatePools?.firstToSecond as any)?.intraday?.state || 'missing' }} · 已有封板/开板字段，不等同于分钟序列</span></div></div><p class="rule-note">竞价和盘中确认仅作为下一交易日待验证项，不渲染买卖信号。</p></section>
  <section v-else class="panel evidence-panel"><h3>基本面与次日验证</h3><div class="missing-module"><strong>基本面：{{ workbench?.fundamentals?.state || 'missing' }}</strong><span>{{ (workbench?.fundamentals?.items as any[])?.length ? '已接入精确日期行情快照中的 PE/PB、市值、换手率和阶段涨跌幅；这些字段不构成财务报表评分。' : '没有已批准的带期间财务事实和可比行业样本。' }}</span></div><div v-if="(workbench?.fundamentals?.items as any[])?.length" class="table-scroll"><table><thead><tr><th>个股</th><th>PE</th><th>PB</th><th>总市值</th><th>换手率</th><th>缺口</th></tr></thead><tbody><tr v-for="item in (workbench?.fundamentals?.items as any[])" :key="item.securityId || item.code"><td>{{ item.name || '--' }}<span>{{ item.code || '--' }}</span></td><td>{{ item.metrics?.pe ?? '--' }}</td><td>{{ item.metrics?.pb ?? '--' }}</td><td>{{ item.metrics?.marketCap ?? '--' }}</td><td>{{ item.metrics?.turnoverRatePct ?? '--' }}</td><td>{{ (item.missingFields || []).join('、') }}</td></tr></tbody></table></div><div class="validation-card"><strong>唯一下一交易日验证</strong><p>{{ workbench?.validation?.check || '先恢复精确日期和规范身份事实，不输出方向性结论。' }}</p><span>确认：{{ workbench?.validation?.confirmation || '--' }}</span><span>失效：{{ workbench?.validation?.invalidation || '--' }}</span></div></section>
</template>

<style scoped>
.workbench-header { margin-bottom: 14px; }
.workbench-meta, .rule-note, .missing-module span, .validation-card span { color: #6f7d77; font-size: 14px; line-height: 1.6; }
.workbench-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }
.workbench-tabs button { min-height: 40px; padding: 8px 12px; border: 1px solid #cfdad5; border-radius: 6px; background: #fff; color: #38544b; cursor: pointer; font-size: 14px; }
.workbench-tabs button.active { border-color: #347b66; background: #e7f2ed; }
.evidence-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.evidence-card { display: flex; min-height: 64px; flex-direction: column; justify-content: center; gap: 5px; padding: 12px; border: 1px solid #dce6e1; border-radius: 6px; background: #fbfdfc; font-size: 14px; }
.evidence-card span { color: #6f7d77; font-size: 14px; }
.selected { background: #eef7f2; }
.missing-module, .validation-card { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; padding: 14px; border: 1px solid #dce6e1; border-radius: 6px; font-size: 14px; line-height: 1.6; }
@media (max-width: 600px) { .evidence-grid { grid-template-columns: 1fr; } .workbench-tabs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); } .workbench-tabs button { min-width: 0; } }
</style>
