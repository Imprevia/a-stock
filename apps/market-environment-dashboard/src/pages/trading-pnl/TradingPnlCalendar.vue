<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { CalendarDays, ChevronLeft, ChevronRight, Upload } from 'lucide-vue-next'
import { currency, errorMessage, issueLabel, ledgerRequest, shanghaiDate, statusText, type LedgerMonth } from '../../trading-pnl'
import './trading-pnl.css'

const route = useRoute()
const router = useRouter()
const openingDate = ref('2026-01-20')
const coverageStart = ref('2026-01-21')
const coverageEnd = ref('2026-01-21')
const coverageKind = ref('complete')
const evidence = ref<File | null>(null)
const month = computed(() => typeof route.query.month === 'string' && /^20\d{2}-(0[1-9]|1[0-2])$/.test(route.query.month)
  ? route.query.month : shanghaiDate().slice(0, 7))
const data = ref<LedgerMonth | null>(null)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const saving = ref(false)
const weekdays = ['一', '二', '三', '四', '五', '六', '日']
const offset = computed(() => (new Date(`${month.value}-01T00:00:00Z`).getUTCDay() + 6) % 7)
const label = computed(() => month.value.replace('-', ' 年 ') + ' 月')
let requestNumber = 0

async function load(): Promise<void> {
  const sequence = ++requestNumber
  loading.value = true
  error.value = ''
  try {
    const result = await ledgerRequest<LedgerMonth>(`/months/${month.value}`)
    if (sequence === requestNumber) data.value = result
  } catch (reason) {
    if (sequence === requestNumber) { error.value = errorMessage(reason); data.value = null }
  } finally {
    if (sequence === requestNumber) loading.value = false
  }
}

function move(offsetMonths: number): void {
  const target = new Date(`${month.value}-01T00:00:00Z`)
  target.setUTCMonth(target.getUTCMonth() + offsetMonths)
  void router.push({ name: 'trading-pnl-calendar', query: { month: target.toISOString().slice(0, 7) } })
}

async function commit(action: () => Promise<void>): Promise<void> {
  if (saving.value) return
  saving.value = true
  notice.value = ''
  error.value = ''
  try { await action() } catch (reason) { error.value = errorMessage(reason) } finally { saving.value = false }
}

async function confirmOpening(): Promise<void> {
  await commit(async () => {
    await ledgerRequest('/opening', { date: openingDate.value, positions: {} })
    const next = new Date(`${openingDate.value}T00:00:00Z`)
    next.setUTCDate(next.getUTCDate() + 1)
    const startMonth = next.toISOString().slice(0, 7)
    if (startMonth === month.value) await load()
    else await router.replace({ query: { month: startMonth } })
    notice.value = '已确认期初空仓。'
  })
}

async function confirmRange(): Promise<void> {
  if (!data.value) return
  await commit(async () => {
    const result = await ledgerRequest<{confirmed_days: number}>('/coverage', {
      start: coverageStart.value, end: coverageEnd.value, kind: coverageKind.value, revision: data.value!.revision,
    })
    await load()
    notice.value = `已确认 ${result.confirmed_days} 天的流水覆盖。`
  })
}

async function uploadEvidence(): Promise<void> {
  if (!evidence.value) return
  await commit(async () => {
    const file = evidence.value!
    if (file.size > 1024 * 1024) throw new Error('盘后证据文件限 1 MB，请分批导入。')
    const content = JSON.parse(await file.text()) as unknown
    await ledgerRequest('/evidence', content)
    evidence.value = null
    await load()
    notice.value = '盘后证据已导入并重新计算。'
  })
}

watch(month, load, { immediate: true })
</script>

<template>
  <section class="pnl-page" aria-labelledby="pnl-calendar-title">
    <header class="pnl-heading">
      <div>
        <h1 id="pnl-calendar-title">盈亏日历</h1>
        <p>模拟交易 · 含持仓涨跌的当日总盈亏</p>
      </div>
      <RouterLink class="pnl-button pnl-primary" :to="{ name: 'trading-pnl-import', query: { month } }">
        <Upload :size="17" aria-hidden="true" /> 导入交易截图
      </RouterLink>
    </header>
    <p v-if="error" class="pnl-message pnl-error" role="alert">{{ error }} <button type="button" class="pnl-button" @click="load">刷新</button></p>
    <p v-if="notice" class="pnl-message" role="status">{{ notice }}</p>
    <form v-if="data && !data.opening_date" class="pnl-panel pnl-form" @submit.prevent="confirmOpening">
      <h2>设置期初</h2>
      <label>收盘空仓日期<input v-model="openingDate" required type="date" :max="shanghaiDate()" /></label>
      <button type="submit" class="pnl-button pnl-primary" :disabled="saving">确认期初空仓</button>
    </form>
    <div class="pnl-panel">
      <div class="pnl-month-toolbar">
        <button type="button" class="pnl-button" aria-label="上一月" :disabled="month === '2000-01'" @click="move(-1)"><ChevronLeft :size="20" /></button>
        <h2><CalendarDays :size="19" aria-hidden="true" /> {{ label }}</h2>
        <button type="button" class="pnl-button" aria-label="下一月" :disabled="month === '2099-12'" @click="move(1)"><ChevronRight :size="20" /></button>
      </div>
      <p v-if="loading" class="pnl-message" role="status">正在读取月历…</p>
      <div v-if="data?.month === month" class="pnl-calendar" aria-label="日历">
        <span v-for="weekday in weekdays" :key="weekday" class="pnl-weekday">{{ weekday }}</span>
        <span v-for="position in offset" :key="`offset-${position}`" aria-hidden="true" />
        <RouterLink v-for="day in data.days" :key="day.date" class="pnl-day-tile"
          :class="{ 'pnl-closed': day.status === 'closed', 'pnl-today': day.date === shanghaiDate() }"
          :aria-label="`${day.date} ${day.pnl === null ? statusText[day.status] : currency(day.pnl)}`"
          :title="day.issues.map(issueLabel).join('，')"
          :to="{ name: 'trading-pnl-day', params: { date: day.date }, query: { month } }">
          <span>{{ Number(day.date.slice(-2)) }}</span>
          <span v-if="day.pnl !== null" class="pnl-day-amount"
            :class="{ 'pnl-positive': Number(day.pnl) > 0, 'pnl-negative': Number(day.pnl) < 0 }">{{ currency(day.pnl) }}</span>
          <span v-else class="pnl-day-state">{{ statusText[day.status] }}</span>
        </RouterLink>
      </div>
      <p v-if="data?.opening_date" class="pnl-muted">期初 {{ data.opening_date }} 收盘</p>
    </div>
    <section v-if="data?.opening_date" class="pnl-panel">
      <h2>确认流水覆盖</h2>
      <p>核对截图或交易记录后，可一次确认一段日期。</p>
      <form class="pnl-form" @submit.prevent="confirmRange">
        <label>起始日期<input v-model="coverageStart" required type="date" :max="shanghaiDate()" /></label>
        <label>结束日期<input v-model="coverageEnd" required type="date" :min="coverageStart" :max="shanghaiDate()" /></label>
        <label>确认内容<select v-model="coverageKind"><option value="complete">期间流水已录全</option><option value="no-trades">期间无成交</option></select></label>
        <button type="submit" class="pnl-button" :disabled="saving">确认覆盖</button>
      </form>
    </section>
    <details class="pnl-panel">
      <summary>导入本地盘后证据</summary>
      <form class="pnl-form" @submit.prevent="uploadEvidence">
        <label>交易日历、收盘价或公司行动 JSON<input type="file" accept="application/json,.json" @change="evidence = ($event.target as HTMLInputElement).files?.[0] ?? null" /></label>
        <button type="submit" class="pnl-button" :disabled="!evidence || saving">导入证据</button>
      </form>
    </details>
  </section>
</template>
