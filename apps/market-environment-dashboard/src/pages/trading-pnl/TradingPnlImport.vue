<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Upload } from 'lucide-vue-next'
import { LEDGER_API, LedgerError, calculationQuery, calculationRequest, errorMessage, issueLabel, ledgerRequest, statusLabel,
  type CalculationResult, type Decision, type Draft, type DraftRow, type ImportResult, type TradeFields } from '../../trading-pnl'
import TradeFieldsForm from './TradeFields.vue'
import './trading-pnl.css'

const route = useRoute()
const router = useRouter()
const resultStorageKey = 'trading-pnl:last-import'
const month = computed(() => typeof route.query.month === 'string' ? route.query.month : undefined)
const returnQuery = computed(() => ({ ...calculationQuery(route.query), month: month.value }))
const files = ref<File[]>([])
const draft = ref<Draft | null>(null)
const decisions = ref<Record<string, Decision | ''>>({})
const reviewed = ref(false)
const busy = ref(false)
const error = ref('')
const result = ref<ImportResult | null>(null)
const batch = ref(calculationQuery(route.query).batch)
const calculation = ref<CalculationResult | null>(null)
const checking = ref(false)
const recoveryNeeded = ref(false)
const calculationError = ref('')
const showCalculationIssues = computed(() => calculation.value && ['retry', 'waiting-settlement', 'partial'].includes(calculation.value.status))
const activeCalculation = computed(() => checking.value || (calculation.value?.status === 'running' && !recoveryNeeded.value))
const imported = computed(() => result.value?.imported ?? [])
const saved = computed(() => result.value?.saved ?? imported.value)
const affectedDates = computed(() => [...new Set(saved.value.map(record => record.date))].sort())
const resultLocation = computed(() => {
  const current = calculation.value
  if (!current?.end || (current.status !== 'complete' && current.status !== 'partial')) return null
  return { name: 'trading-pnl-calendar', query: { batch: batch.value, start: current.start, end: current.end, month: current.end.slice(0, 7) } }
})
const imageRatios = ref<Record<string, number>>({})
const rows = computed(() => draft.value?.images.flatMap(image => image.rows) ?? [])
const selected = computed(() => rows.value.filter(row => decisions.value[key(row)]))
const ready = computed(() => reviewed.value && selected.value.length > 0 && selected.value.every(row =>
  decisions.value[key(row)] === 'skip' || (!row.issues.length && !row.blocked && (!row.matches.length || decisions.value[key(row)] === 'keep-distinct'))))
let requestKey: string | null = null
let pollTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false

onMounted(() => {
  if (!batch.value) return
  try {
    const saved: ImportResult | null = JSON.parse(sessionStorage.getItem(resultStorageKey) ?? 'null')
    if (saved?.batch_id === batch.value) result.value = saved
  } catch { /* 批次状态仍可通过 API 恢复。 */ }
  void checkCalculation(false)
})
onUnmounted(() => {
  disposed = true
  clearTimeout(pollTimer)
})

async function applyCalculation(current: CalculationResult, openResult: boolean): Promise<void> {
  if (disposed) return
  calculation.value = current
  if (current.status === 'running') {
    pollTimer = setTimeout(() => void checkCalculation(true), 1500)
  } else if (openResult && resultLocation.value) {
    await router.push(resultLocation.value)
  }
}

async function checkCalculation(openResult: boolean): Promise<void> {
  if (!batch.value || checking.value || disposed) return
  checking.value = true
  recoveryNeeded.value = false
  calculationError.value = ''
  try {
    await applyCalculation(await calculationRequest(batch.value), openResult)
  } catch (reason) {
    if (reason instanceof LedgerError && reason.status === 404) {
      if (calculation.value?.status === 'running') calculation.value = null
      if (openResult) calculationError.value = '暂未找到本批计算，请再次点击计算盈亏。'
    } else {
      recoveryNeeded.value = true
      calculationError.value = `无法读取计算状态。${errorMessage(reason)}`
    }
  } finally {
    checking.value = false
  }
}

async function calculate(): Promise<void> {
  if (!batch.value || busy.value || activeCalculation.value || recoveryNeeded.value) return
  checking.value = true
  calculationError.value = ''
  try {
    await applyCalculation(await calculationRequest(batch.value, 'POST'), true)
  } catch {
    checking.value = false
    await checkCalculation(true)
  } finally {
    checking.value = false
  }
}

function key(row: DraftRow): string { return `${row.digest}:${row.row_number}` }

function imageRatio(digest: string, event: Event): void {
  const image = event.target as HTMLImageElement
  if (image.naturalHeight) imageRatios.value[digest] = image.naturalWidth / image.naturalHeight
}

function setFiles(event: Event): void {
  const input = event.target as HTMLInputElement
  files.value = Array.from(input.files ?? [])
}

function choose(row: DraftRow, choice: Decision | ''): void {
  decisions.value[key(row)] = choice
  requestKey = null
}

function edit(row: DraftRow, fields: TradeFields): void {
  row.fields = fields
  reviewed.value = false
  requestKey = null
}

async function run(action: () => Promise<void>): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await action() } catch (reason) { error.value = errorMessage(reason) } finally { busy.value = false }
}

async function upload(): Promise<void> {
  if (activeCalculation.value) return
  await run(async () => {
    if (!files.value.length || files.value.length > 6 || files.value.some(file => file.size > 5 * 1024 * 1024)) {
      throw new Error('请选择 1 至 6 张截图，每张不超过 5 MB。')
    }
    const form = new FormData()
    files.value.forEach(file => form.append('images', file))
    draft.value = await ledgerRequest<Draft>('/drafts', form)
    requestKey = null
    decisions.value = {}
    reviewed.value = true
    result.value = null
    calculation.value = null
    batch.value = undefined
    recoveryNeeded.value = false
    calculationError.value = ''
    await router.replace({ query: { month: month.value } })
  })
}

function values(row: DraftRow) {
  return { digest: row.digest, row_number: row.row_number, fields: row.fields }
}

async function refreshPreview(): Promise<void> {
  if (!draft.value) return
  draft.value = await ledgerRequest<Draft>(`/drafts/${draft.value.id}/preview`, { rows: rows.value.map(values) })
  reviewed.value = true
  requestKey = null
  decisions.value = Object.fromEntries(rows.value.filter(row => decisions.value[key(row)] === 'skip').map(row => [key(row), 'skip']))
}

function chooseClearRows(): void {
  rows.value.filter(row => !row.matches.length && !row.issues.length && !row.blocked).forEach(row => choose(row, 'add'))
}

function newRequestKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
}

async function confirm(): Promise<void> {
  if (!draft.value || !ready.value) return
  await run(async () => {
    requestKey ??= newRequestKey()
    try {
      const confirmed = await ledgerRequest<ImportResult>(`/drafts/${draft.value!.id}/confirm`, {
        key: requestKey, revision: draft.value!.revision,
        rows: selected.value.map(row => ({ ...values(row), decision: decisions.value[key(row)] })),
      })
      result.value = confirmed
      batch.value = confirmed.batch_id ?? undefined
      draft.value = null
      if (batch.value) {
        try {
          sessionStorage.setItem(resultStorageKey, JSON.stringify(confirmed))
        } catch { /* 已确认批次仍可通过 API 恢复计算状态。 */ }
        await router.replace({ query: { month: month.value, batch: batch.value } })
      }
    } catch (reason) {
      if (reason instanceof LedgerError && reason.status === 409) {
        await refreshPreview()
      }
      throw reason
    }
  })
}

function matchLabel(kind: string): string {
  return ({ 'same-image': '相同截图记录已入账', 'same-id': '相同编号已入账', 'id-conflict': '相同编号的内容有冲突',
    'batch-id': '本批次相同编号', 'batch-possible': '本批次疑似重复', possible: '已有相似记录' } as Record<string, string>)[kind] ?? kind
}
</script>

<template>
  <section class="pnl-page" aria-labelledby="pnl-import-title">
    <RouterLink class="pnl-back" :to="{ name: 'trading-pnl-calendar', query: returnQuery }"><ArrowLeft :size="17" /> 返回盈亏日历</RouterLink>
    <header class="pnl-heading"><div><h1 id="pnl-import-title">导入交易截图</h1><p>核对原图、成交字段和重复项后，选择要入账的记录。</p></div></header>
    <p v-if="error" class="pnl-message pnl-error" role="alert">{{ error }}</p>
    <form class="pnl-panel pnl-form" @submit.prevent="upload">
      <label>选择已展开交易月份的截图<input type="file" accept="image/png,image/jpeg" multiple @change="setFiles" /></label>
      <button class="pnl-button pnl-primary" type="submit" :disabled="!files.length || busy || activeCalculation"><Upload :size="17" /> {{ busy && !draft ? '正在识别…' : '识别截图' }}</button>
    </form>
    <section v-if="result || batch" class="pnl-panel" aria-labelledby="pnl-import-result">
      <h2 id="pnl-import-result">入账完成</h2>
      <p v-if="result" role="status">新增 {{ saved.length }} 笔，跳过 {{ result.skipped.length }} 笔。</p>
      <div v-if="imported.length" class="pnl-table-wrap">
        <table class="pnl-table" aria-label="已入账记录">
          <thead><tr><th scope="col">交易日期</th><th scope="col">证券</th><th scope="col">方向</th><th scope="col">成交股数</th><th scope="col">单价</th></tr></thead>
          <tbody><tr v-for="trade in imported" :key="trade.id">
            <td>{{ trade.date }}</td>
            <td>{{ trade.name || trade.security }} <small v-if="trade.name">{{ trade.security }}</small></td>
            <td>{{ trade.side === 'buy' ? '买入' : trade.side === 'sell' ? '卖出' : trade.side }}</td>
            <td>{{ trade.quantity }}</td><td>{{ trade.price ?? '—' }}</td>
          </tr></tbody>
        </table>
      </div>
      <div v-if="batch" class="pnl-inline">
        <button v-if="recoveryNeeded" class="pnl-button pnl-primary" type="button" :disabled="checking || busy" @click="checkCalculation(true)">恢复查询</button>
        <button v-else class="pnl-button pnl-primary" type="button" :disabled="busy || activeCalculation" @click="calculate">
          {{ activeCalculation ? '正在计算…' : calculation ? '重新计算盈亏' : '计算盈亏' }}
        </button>
        <RouterLink v-if="resultLocation" class="pnl-button" :to="resultLocation">查看计算结果</RouterLink>
      </div>
      <p v-if="activeCalculation" role="status">正在读取或计算本批盘后盈亏…</p>
      <p v-if="calculationError" role="alert" class="pnl-message pnl-error">{{ calculationError }}</p>
      <p v-if="calculation?.status === 'waiting-settlement'" class="pnl-message" role="status">
        从 {{ calculation.start }} 起尚无已结算交易日，请待结算后重新计算。
      </p>
      <p v-if="calculation?.status === 'retry'" class="pnl-message" role="status">本批计算待重试，已入账记录可继续查询。</p>
      <p v-if="calculation?.status === 'partial' && !calculation.end" class="pnl-message" role="status">
        自 {{ calculation.start }} 起的交易日历仍有缺项，当前无法确定已结算范围。可重新计算。
      </p>
      <ul v-if="showCalculationIssues && calculation?.missing.length" class="pnl-issues">
        <li v-for="(item, index) in calculation.missing" :key="index">
          {{ item.date }}<template v-if="item.security"> · {{ item.security }}</template> · {{ issueLabel(item.reason) }}
        </li>
      </ul>
      <nav v-if="affectedDates.length" class="pnl-inline" aria-label="核对已入账流水">
        <RouterLink v-for="affected in affectedDates" :key="affected" class="pnl-back"
          :to="{ name: 'trading-pnl-day', params: { date: affected }, query: returnQuery }">核对 {{ affected }} 流水</RouterLink>
      </nav>
    </section>
    <template v-if="draft">
      <section v-for="(image, index) in draft.images" :key="image.digest" class="pnl-panel">
        <h2>截图 {{ index + 1 }}</h2>
        <details class="pnl-original"><summary>查看原图</summary>
          <img :src="`${LEDGER_API}/drafts/${draft.id}/images/${image.digest}`" :alt="`待核对交易截图 ${index + 1}`" />
        </details>
        <ul v-if="image.hints.length" class="pnl-positions pnl-muted"><li v-for="hint in image.hints" :key="hint">{{ hint }}</li></ul>
        <p v-if="!image.rows.length">没有识别到交易行，请检查月份是否展开且截图是否完整。</p>
        <article v-for="row in image.rows" :key="row.row_number" class="pnl-edit">
          <h3>记录 {{ row.row_number + 1 }} · {{ row.fields.name || row.fields.security || '待识别证券' }}</h3>
          <details class="pnl-original"><summary>查看原图对应行和识别原文</summary>
            <div class="pnl-line-preview" :class="{ cropped: imageRatios[image.digest] }"
              :style="{ aspectRatio: imageRatios[image.digest] ? `${imageRatios[image.digest] / (row.region[1] - row.region[0])}` : undefined }">
              <img :src="`${LEDGER_API}/drafts/${draft.id}/images/${image.digest}`" alt="原图对应交易行" loading="lazy"
                :style="{ transform: imageRatios[image.digest] ? `translateY(${-row.region[0] * 100}%)` : undefined }"
                @load="imageRatio(image.digest, $event)" />
            </div>
            <p class="pnl-raw">{{ row.raw }}</p>
          </details>
          <TradeFieldsForm :model-value="row.fields" @update:model-value="edit(row, $event)" />
          <ul v-if="row.issues.length && reviewed" class="pnl-issues"><li v-for="issue in row.issues" :key="issue">{{ issue }}</li></ul>
          <ul v-if="row.matches.length" class="pnl-issues">
            <li v-for="(match, matchIndex) in row.matches" :key="matchIndex">
              <strong>{{ matchLabel(match.kind) }}</strong> {{ match.id != null ? `#${match.id}` : '' }}
              · {{ match.fields.date }} · {{ match.fields.security }} · {{ match.fields.side === 'buy' ? '买入' : '卖出' }} {{ match.fields.filled_quantity }} 股
              · {{ match.fields.price ?? '—' }} · {{ statusLabel(String(match.fields.status)) }}
            </li>
          </ul>
          <label class="pnl-select-decision">入账选择
            <select :value="decisions[key(row)] ?? ''" @change="choose(row, ($event.target as HTMLSelectElement).value as Decision | '')">
              <option value="">待处理</option><option value="skip">跳过</option>
              <option v-if="!row.blocked && !row.matches.length" value="add">确认入账</option>
              <option v-if="!row.blocked && row.matches.length" value="keep-distinct">确认是另一笔，保留</option>
            </select>
          </label>
        </article>
      </section>
      <div class="pnl-panel pnl-inline" v-if="rows.length">
        <button class="pnl-button" type="button" :disabled="busy" @click="run(refreshPreview)">重新核对识别结果</button>
        <button class="pnl-button" type="button" :disabled="busy || !reviewed" @click="chooseClearRows">选择无疑问记录</button>
        <button class="pnl-button pnl-primary" type="button" :disabled="busy || !ready" @click="confirm">确认本批 {{ selected.length }} 条选择</button>
        <p v-if="!reviewed" class="pnl-muted">字段有修改，请重新核对后提交。</p>
      </div>
    </template>
  </section>
</template>
