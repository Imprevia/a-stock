<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ArrowLeft, Upload } from 'lucide-vue-next'
import { LEDGER_API, LedgerError, errorMessage, ledgerRequest, statusLabel, type Decision, type Draft, type DraftRow, type TradeFields } from '../../trading-pnl'
import TradeFieldsForm from './TradeFields.vue'
import './trading-pnl.css'

const route = useRoute()
const month = computed(() => typeof route.query.month === 'string' ? route.query.month : undefined)
const files = ref<File[]>([])
const draft = ref<Draft | null>(null)
const decisions = ref<Record<string, Decision | ''>>({})
const reviewed = ref(false)
const busy = ref(false)
const error = ref('')
const result = ref<{ saved: { id: number; date: string }[]; skipped: unknown[] } | null>(null)
const imageRatios = ref<Record<string, number>>({})
const rows = computed(() => draft.value?.images.flatMap(image => image.rows) ?? [])
const selected = computed(() => rows.value.filter(row => decisions.value[key(row)]))
const ready = computed(() => reviewed.value && selected.value.length > 0 && selected.value.every(row =>
  decisions.value[key(row)] === 'skip' || (!row.issues.length && !row.blocked && (!row.matches.length || decisions.value[key(row)] === 'keep-distinct'))))
let requestKey: string | null = null

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
      result.value = await ledgerRequest(`/drafts/${draft.value!.id}/confirm`, {
        key: requestKey, revision: draft.value!.revision,
        rows: selected.value.map(row => ({ ...values(row), decision: decisions.value[key(row)] })),
      })
      draft.value = null
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
    <RouterLink class="pnl-back" :to="{ name: 'trading-pnl-calendar', query: { month } }"><ArrowLeft :size="17" /> 返回盈亏日历</RouterLink>
    <header class="pnl-heading"><div><h1 id="pnl-import-title">导入交易截图</h1><p>核对原图、成交字段和重复项后，选择要入账的记录。</p></div></header>
    <p v-if="error" class="pnl-message pnl-error" role="alert">{{ error }}</p>
    <form class="pnl-panel pnl-form" @submit.prevent="upload">
      <label>选择已展开交易月份的截图<input type="file" accept="image/png,image/jpeg" multiple @change="setFiles" /></label>
      <button class="pnl-button pnl-primary" type="submit" :disabled="!files.length || busy"><Upload :size="17" /> {{ busy && !draft ? '正在识别…' : '识别截图' }}</button>
    </form>
    <section v-if="result" class="pnl-panel" role="status">
      <h2>入账完成</h2><p>新增 {{ result.saved.length }} 笔，跳过 {{ result.skipped.length }} 笔。</p>
      <RouterLink v-for="record in result.saved" :key="record.id" class="pnl-back" :to="{ name: 'trading-pnl-day', params: { date: record.date }, query: { month } }">查看 {{ record.date }} 记录 {{ record.id }}</RouterLink>
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
