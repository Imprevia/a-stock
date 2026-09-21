<script setup lang="ts">
/**
 * Document03LimitsPage — 第 03 章 涨停、跌停、炸板和晋级。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '03'"`
 * block in Phase B-03 of frontend-component-split. Reads exclusively from
 * `useMarketStore()` + `useDocumentContext()` so the component can be
 * mounted independently. Writes (section refresh) go through emit.
 */
import { AlertTriangle, CircleAlert, Database as DatabaseIcon, LineChart as LineChartIcon, RefreshCw, Rows3, Scale, ShieldAlert } from 'lucide-vue-next'
import { computed } from 'vue'

import LimitSecurityDetailsPanel from '../../components/limits/LimitSecurityDetailsPanel.vue'
import { formatDateTime as fmtDateTime } from '../../composables/useFormatDateTime'
import { usePreferencesStore } from '../../stores/preferences'
import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'

const market = useMarketStore()
const ctx = useDocumentContext()
const preferences = usePreferencesStore()

const limits = computed(() => market.limits)
const sectionLoading = computed(() => market.sectionStates.limits.phase === 'loading' || market.sectionStates.limits.phase === 'refreshing')
const sectionError = computed(() => market.sectionStates.limits.error)
const sectionPhase = computed(() => ctx.limitSectionPhase.value)

const emit = defineEmits<{
  refreshSection: []
}>()

function onRefreshSection(): void {
  emit('refreshSection')
}

function formatCount(value: number | null | undefined): string {
  return value == null ? '--' : value.toLocaleString('zh-CN')
}

function formatPosition(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(0)}%`
}

function formatEvidenceTime(value: string | null | undefined): string {
  return fmtDateTime(value, { precision: 'second', timeZone: preferences.effectiveTimeZone })
}

function percentLabel(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(2)}%`
}

const metricNullList = computed(() => [
  limits.value?.limitUpCount,
  limits.value?.limitDownCount,
  limits.value?.failedLimitUpCount,
  limits.value?.failedLimitUpRatio,
  limits.value?.maxStreak,
].some((value) => value == null))
</script>

<template>
  <p class="page-flow-label">事实 → 判断 → 质量边界</p>

  <section class="limits-quality-band" aria-label="涨跌停数据质量">
    <div class="limits-quality-heading">
      <div><span class="panel-kicker">本节证据 · 质量优先</span><h2>涨跌停数据集</h2></div>
      <div class="limits-quality-actions">
        <span class="quality-badge" :class="ctx.qualityTone(limits?.quality)">{{ ctx.sectionPhaseLabel(sectionPhase) }}</span>
        <button class="icon-button" type="button" :disabled="sectionLoading" aria-label="刷新涨跌停证据" title="刷新涨跌停证据" @click="onRefreshSection">
          <RefreshCw :size="17" :class="{ spin: sectionLoading }" />
        </button>
      </div>
    </div>
    <div class="limits-quality-primary">
      <div><span>所选交易日</span><strong>{{ market.data?.asOf ?? '--' }}</strong></div>
      <div><span>数据质量</span><strong>{{ ctx.qualityCodeLabel(limits?.quality) }}</strong></div>
      <div><span>数据提供方</span><strong>{{ limits?.quality.provider || '--' }}</strong></div>
      <div><span>缓存状态</span><strong>{{ ctx.cacheStateLabel(limits?.quality.cacheState) }}</strong></div>
    </div>
    <div class="limits-quality-secondary">
      <div><span>样本实际日期</span><strong>{{ limits?.quality.asOf || '--' }}</strong></div>
      <div><span>有效观察数</span><strong>{{ formatCount(limits?.quality.observations) }}</strong></div>
      <div><span>数据来源</span><strong>{{ limits?.quality.source || '--' }}</strong></div>
      <div><span>抓取时间</span><strong :title="market.data?.generatedAt">{{ formatEvidenceTime(limits?.quality.snapshotFetchedAt) }}</strong></div>
    </div>
    <div v-if="sectionError" class="limits-refresh-error" role="alert">
      <CircleAlert :size="17" />
      <span>刷新失败，继续显示同日期最后一次证据：{{ sectionError }}</span>
      <button class="text-button" type="button" @click="onRefreshSection">重试</button>
    </div>
    <div class="limits-warning-block" :class="{ empty: !ctx.limitWarnings.value.length }">
      <AlertTriangle :size="17" />
      <div><strong>数据警告</strong><span>{{ ctx.limitWarnings.value.length ? ctx.limitWarnings.value.join('；') : '无' }}</span></div>
    </div>
  </section>

  <section class="metric-grid five">
    <article class="metric-card"><span>涨停</span><strong class="positive">{{ formatCount(limits?.limitUpCount) }}</strong></article>
    <article class="metric-card"><span>跌停</span><strong class="negative">{{ formatCount(limits?.limitDownCount) }}</strong></article>
    <article class="metric-card"><span>炸板</span><strong>{{ formatCount(limits?.failedLimitUpCount) }}</strong></article>
    <article class="metric-card"><span>炸板率</span><strong>{{ percentLabel(limits?.failedLimitUpRatio) }}</strong></article>
    <article class="metric-card"><span>最高连板</span><strong>{{ limits?.maxStreak == null ? '--' : `${limits.maxStreak} 板` }}</strong></article>
  </section>
  <div v-if="metricNullList" class="limits-null-note">
    <CircleAlert :size="17" />
    <span>“--”表示数据不可用或分母不可计算，不代表 0。</span>
  </div>

  <LimitSecurityDetailsPanel :details="limits?.securityDetails" />

  <section class="limits-promotion-grid">
    <article class="panel limit-promotion-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">跨交易日 · 后端直出</span><h2>连板晋级证据</h2></div>
        <span class="quality-badge" :class="ctx.metricQualityTone(limits?.promotionQuality?.status)">{{ ctx.metricQualityLabel(limits?.promotionQuality?.status) }}</span>
      </div>
      <div class="promotion-summary">
        <div class="promotion-ratio"><span>晋级率</span><strong>{{ percentLabel(limits?.promotionRatio) }}</strong></div>
        <div><span>今日晋级</span><strong>{{ formatCount(limits?.todayPromoted) }}</strong></div>
        <div><span>昨日合格样本</span><strong>{{ formatCount(limits?.yesterdayLimitUpEligible) }}</strong></div>
      </div>
      <p v-if="ctx.promotionGap.value" class="promotion-gap"><CircleAlert :size="17" />{{ ctx.promotionGap.value }}</p>
      <dl class="promotion-metadata">
        <div><dt>当前样本日期</dt><dd>{{ limits?.promotionSampleAsOf || '--' }}</dd></div>
        <div><dt>前一样本日期</dt><dd>{{ limits?.promotionPreviousAsOf || '--' }}</dd></div>
        <div><dt>样本规则</dt><dd>{{ limits?.promotionSampleRule || '--' }}</dd></div>
        <div><dt>规则版本</dt><dd>{{ limits?.promotionRuleVersion || '--' }}</dd></div>
      </dl>
    </article>
    <article class="panel limit-field-quality-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">字段证据</span><h2>晋级字段质量</h2></div>
      </div>
      <div class="field-quality-list">
        <div>
          <span>今日晋级</span>
          <strong>{{ ctx.metricQualityLabel(limits?.fieldQuality?.todayPromoted?.status) }}</strong>
          <small>{{ limits?.fieldQuality?.todayPromoted?.reason || '未提供字段质量' }} · 观察 {{ formatCount(limits?.fieldQuality?.todayPromoted?.observations) }}</small>
        </div>
        <div>
          <span>昨日合格样本</span>
          <strong>{{ ctx.metricQualityLabel(limits?.fieldQuality?.yesterdayLimitUpEligible?.status) }}</strong>
          <small>{{ limits?.fieldQuality?.yesterdayLimitUpEligible?.reason || '未提供字段质量' }} · 观察 {{ formatCount(limits?.fieldQuality?.yesterdayLimitUpEligible?.observations) }}</small>
        </div>
        <div>
          <span>晋级率</span>
          <strong>{{ ctx.metricQualityLabel(limits?.fieldQuality?.promotionRatio?.status) }}</strong>
          <small>{{ limits?.fieldQuality?.promotionRatio?.reason || '未提供字段质量' }} · 观察 {{ formatCount(limits?.fieldQuality?.promotionRatio?.observations) }}</small>
        </div>
      </div>
      <div class="promotion-quality-source">
        <span>晋级来源</span><strong>{{ limits?.promotionQuality?.source || '--' }}</strong>
        <span>晋级观察数</span><strong>{{ formatCount(limits?.promotionQuality?.observations) }}</strong>
      </div>
    </article>
  </section>

  <section class="limits-evidence-grid">
    <article class="panel limit-table-panel">
      <div class="panel-heading"><div><span class="panel-kicker">接力结构</span><h2>首板至四板以上梯队</h2></div></div>
      <div v-if="ctx.limitTiers.value.length" class="table-scroll">
        <table class="limits-table tier-table">
          <thead><tr><th>梯队</th><th>数量</th><th>观察数</th><th>质量</th></tr></thead>
          <tbody>
            <tr v-for="row in ctx.limitTiers.value" :key="row.tier">
              <td><strong>{{ row.label || row.tier }}</strong></td>
              <td>{{ formatCount(row.count) }}</td>
              <td>{{ formatCount(row.observations) }}</td>
              <td>{{ ctx.metricQualityLabel(row.quality?.status) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-evidence compact">
        <Rows3 :size="22" />
        <strong>梯队证据不足</strong>
        <p>首板、二板、三板和四板以上数量尚未形成可追溯数据。</p>
      </div>
    </article>
    <article class="panel limit-table-panel">
      <div class="panel-heading"><div><span class="panel-kicker">样本结构</span><h2>制度与板块分层</h2></div></div>
      <div v-if="ctx.limitStratifications.value.length" class="stratification-groups">
        <section v-for="group in ctx.limitStratifications.value" :key="group.label">
          <h3>{{ group.label }}</h3>
          <div class="table-scroll">
            <table class="limits-table">
              <thead><tr><th>分层</th><th>数量</th><th>观察数</th><th>质量</th></tr></thead>
              <tbody>
                <tr v-for="row in group.rows" :key="row.key">
                  <td><strong>{{ row.label || row.key }}</strong></td>
                  <td>{{ formatCount(row.count) }}</td>
                  <td>{{ formatCount(row.observations) }}</td>
                  <td>{{ ctx.metricQualityLabel(row.quality?.status) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <div v-else class="empty-evidence compact">
        <DatabaseIcon :size="22" />
        <strong>分层证据不足</strong>
        <p>涨跌幅制度、市场板块、ST 与上市窗口样本尚未完整验证。</p>
      </div>
    </article>
  </section>

  <section class="panel limit-history-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">连续性证据</span><h2>近 5 个已验证交易日</h2></div>
      <span class="quality-badge" :class="ctx.metricQualityTone(ctx.limitHistoryMeta.value?.quality?.status)">{{ ctx.metricQualityLabel(ctx.limitHistoryMeta.value?.quality?.status) }}</span>
    </div>
    <div v-if="ctx.limitHistory.value.length" class="table-scroll">
      <table class="limits-table history-table">
        <thead><tr><th>日期</th><th>涨停</th><th>跌停</th><th>炸板率</th><th>晋级率</th><th>最高板</th></tr></thead>
        <tbody>
          <tr v-for="point in ctx.limitHistory.value" :key="point.asOf">
            <td><strong>{{ point.asOf }}</strong></td>
            <td>{{ formatCount(point.limitUpCount) }}</td>
            <td>{{ formatCount(point.limitDownCount) }}</td>
            <td>{{ percentLabel(point.failedLimitUpRatio) }}</td>
            <td>{{ percentLabel(point.promotionRatio) }}</td>
            <td>{{ point.maxStreak == null ? '--' : `${point.maxStreak} 板` }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty-evidence compact">
      <LineChartIcon :size="22" />
      <strong>历史窗口不足</strong>
      <p>只展示精确交易日快照，不使用其他日期回填。当前有效观察 {{ formatCount(ctx.limitHistoryMeta.value?.validObservations) }} / {{ formatCount(ctx.limitHistoryMeta.value?.requiredObservations ?? 60) }}。</p>
    </div>
    <div v-if="ctx.limitHistoryMeta.value?.percentile250" class="limit-percentile">
      <div><span>250 日有效观察</span><strong>{{ formatCount(ctx.limitHistoryMeta.value?.validObservations) }} / {{ formatCount(ctx.limitHistoryMeta.value?.requiredObservations ?? 60) }}</strong></div>
      <div><span>涨停家数分位</span><strong>{{ formatPosition(ctx.limitHistoryMeta.value.percentile250.limitUpCount) }}</strong></div>
      <div><span>跌停家数分位</span><strong>{{ formatPosition(ctx.limitHistoryMeta.value.percentile250.limitDownCount) }}</strong></div>
      <div><span>炸板率分位</span><strong>{{ formatPosition(ctx.limitHistoryMeta.value.percentile250.failedLimitUpRatio) }}</strong></div>
      <div><span>晋级率分位</span><strong>{{ formatPosition(ctx.limitHistoryMeta.value.percentile250.promotionRatio) }}</strong></div>
      <div><span>最高板分位</span><strong>{{ formatPosition(ctx.limitHistoryMeta.value.percentile250.maxStreak) }}</strong></div>
    </div>
  </section>

  <section class="limits-evidence-grid">
    <article class="panel limit-rule-panel">
      <div class="panel-heading"><div><span class="panel-kicker">经验规则 · 待回测</span><h2>规则证据</h2></div></div>
      <div v-if="limits?.ruleEvidence?.length" class="limit-rule-list">
        <div v-for="rule in limits.ruleEvidence" :key="rule.ruleId">
          <span>{{ rule.ruleId }}</span>
          <strong>{{ rule.score == null ? '分数不足' : `${rule.score.toFixed(1)} 分` }}</strong>
          <small>{{ rule.calibrationStatus === 'validated' ? '已验证' : '待回测' }} · 权重 {{ rule.weight == null ? '--' : formatPosition(rule.weight) }}</small>
          <ul v-if="rule.evidence?.length"><li v-for="item in rule.evidence" :key="item">{{ item }}</li></ul>
        </div>
      </div>
      <div v-else class="empty-evidence compact">
        <Scale :size="22" />
        <strong>规则输入不足</strong>
        <p>不把缺失输入视为零风险，也不生成自动交易建议。</p>
      </div>
    </article>
    <article class="panel limit-risk-panel">
      <div class="panel-heading"><div><span class="panel-kicker">风险与复核</span><h2>{{ limits?.state || '数据不足' }}</h2></div></div>
      <div v-if="limits?.riskEvidence?.length" class="risk-evidence-list">
        <div v-for="item in limits.riskEvidence" :key="`${item.label}-${item.asOf}`">
          <span>{{ item.label }}</span>
          <strong>{{ item.value ?? '--' }}</strong>
          <small>{{ item.asOf || '--' }} · {{ ctx.metricQualityLabel(item.quality?.status ?? item.status) }}</small>
          <ul v-if="item.evidence?.length"><li v-for="evidence in item.evidence" :key="evidence">{{ evidence }}</li></ul>
        </div>
      </div>
      <div v-else class="empty-evidence compact">
        <ShieldAlert :size="22" />
        <strong>风险证据不足</strong>
        <p>连续跌停、断板修复和板块集中输入不完整时不形成周期结论。</p>
      </div>
      <dl class="limit-verification">
        <div><dt>次日确认</dt><dd>{{ limits?.confirmation || '等待新增证据' }}</dd></div>
        <div><dt>失效条件</dt><dd>{{ limits?.invalidation || '尚未形成可追溯条件' }}</dd></div>
      </dl>
    </article>
  </section>
</template>
