<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import { amount, currency, errorMessage, issueLabel, ledgerRequest, statusLabel, statusText, type LedgerDay, type LedgerRecord, type TradeFields } from '../../trading-pnl'
import TradeFieldsForm from './TradeFields.vue'
import './trading-pnl.css'

const route = useRoute()
const router = useRouter()
const date = computed(() => String(route.params.date))
const originMonth = computed(() => typeof route.query.month === 'string' ? route.query.month : date.value.slice(0, 7))
const day = ref<LedgerDay | null>(null)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const saving = ref(false)
const editing = ref<LedgerRecord | null>(null)
const fields = ref<TradeFields>({})
const keepDistinct = ref(false)
const components = [
  ['opening_value', '上一交易日收盘市值'], ['closing_value', '当日收盘市值'],
  ['buy_cost', '含费买入支出'], ['sell_proceeds', '净卖出收入'], ['commission', '佣金合计'],
  ['other_fees', '其他费用合计'], ['cash_adjustment', '应计现金调整'],
]
let requestNumber = 0

async function load(after = 0): Promise<void> {
  const sequence = ++requestNumber
  loading.value = true
  error.value = ''
  try {
    const result = await ledgerRequest<LedgerDay>(`/days/${date.value}?after=${after}`)
    if (sequence !== requestNumber) return
    if (after && day.value?.revision !== result.revision) {
      await load()
      notice.value = '台账已更新，已重新读取当天记录。'
      return
    }
    day.value = after && day.value ? { ...result, trades: [...day.value.trades, ...result.trades] } : result
  } catch (reason) {
    if (sequence === requestNumber) error.value = errorMessage(reason)
  } finally {
    if (sequence === requestNumber) loading.value = false
  }
}

async function save(action: () => Promise<void>): Promise<void> {
  if (saving.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try { await action() } catch (reason) { error.value = errorMessage(reason) } finally { saving.value = false }
}

function begin(record: LedgerRecord): void {
  const { id, revision, source, ...values } = record
  editing.value = record
  fields.value = values
  keepDistinct.value = false
}

async function saveCorrection(): Promise<void> {
  if (!editing.value) return
  const record = editing.value
  const target = String(fields.value.date)
  await save(async () => {
    await ledgerRequest(`/trades/${record.id}/correction`, { revision: record.revision, trade: fields.value, keep_distinct: keepDistinct.value })
    editing.value = null
    if (target !== date.value) await router.push({ params: { date: target }, query: { month: originMonth.value } })
    else await load()
    notice.value = '更正已入账，请重新核对受影响日期的流水覆盖。'
  })
}

async function setCoverage(kind: string): Promise<void> {
  if (!day.value) return
  await save(async () => {
    await ledgerRequest('/coverage', { start: date.value, end: date.value, kind, revision: day.value!.revision })
    await load()
    notice.value = '已确认当日流水覆盖。'
  })
}

watch(date, () => { day.value = null; editing.value = null; void load() }, { immediate: true })
</script>

<template>
  <section class="pnl-page" aria-labelledby="pnl-day-title">
    <RouterLink class="pnl-back" :to="{ name: 'trading-pnl-calendar', query: { month: originMonth } }"><ArrowLeft :size="17" /> 返回盈亏日历</RouterLink>
    <header class="pnl-heading">
      <div><h1 id="pnl-day-title">{{ date }} 交易明细</h1><p>当日总盈亏</p></div>
      <RouterLink class="pnl-button pnl-primary" :to="{ name: 'trading-pnl-import', query: { month: originMonth } }">导入交易截图</RouterLink>
    </header>
    <p v-if="error" class="pnl-message pnl-error" role="alert">{{ error }} <button class="pnl-button" type="button" @click="load()">刷新</button></p>
    <p v-if="notice" class="pnl-message" role="status">{{ notice }}</p>
    <p v-if="loading" role="status">正在读取交易明细…</p>
    <template v-if="day">
      <section class="pnl-panel">
        <h2 class="pnl-total" :class="{ 'pnl-positive': Number(day.pnl) > 0, 'pnl-negative': Number(day.pnl) < 0 }">
          {{ day.pnl === null ? statusText[day.status] : currency(day.pnl) }}
        </h2>
        <p v-if="day.previous_date" class="pnl-muted">上一交易日 {{ day.previous_date }}</p>
        <ul v-if="day.issues.length" class="pnl-issues">
          <li v-for="issue in day.issues" :key="issue">{{ issueLabel(issue) }}</li>
        </ul>
        <dl v-if="day.components" class="pnl-metrics">
          <div v-for="[key, label] in components" :key="key"><dt>{{ label }}</dt><dd>{{ amount(day.components[key]) }}</dd></div>
        </dl>
        <p v-if="day.coverage" class="pnl-muted">{{ day.coverage === 'no-trades' ? '已确认无成交' : '已确认流水完整' }}</p>
        <div v-if="day.status === 'insufficient' || day.status === 'ok'" class="pnl-inline">
          <button class="pnl-button" type="button" :disabled="saving || day.coverage === 'complete'" @click="setCoverage('complete')">确认当日流水已录全</button>
          <button class="pnl-button" type="button" :disabled="saving || day.coverage === 'no-trades' || day.trades.some(row => Number(row.filled_quantity) > 0)" @click="setCoverage('no-trades')">确认无成交</button>
        </div>
      </section>
      <section class="pnl-panel">
        <h2>交易记录</h2>
        <p v-if="!day.trades.length" class="pnl-muted">暂无已入账记录。</p>
        <div v-else class="pnl-table-wrap">
          <table class="pnl-table">
            <thead><tr><th>证券</th><th>方向与状态</th><th>成交股数</th><th>单价</th><th>成交额</th><th>时间</th><th>操作</th></tr></thead>
            <tbody><tr v-for="trade in day.trades" :key="trade.id">
              <td>{{ trade.name || trade.security }} <small>{{ trade.name ? trade.security : '' }}</small></td>
              <td>{{ trade.side === 'buy' ? '买入' : '卖出' }} · {{ statusLabel(String(trade.status)) }}</td>
              <td>{{ trade.filled_quantity }}</td><td>{{ trade.price ?? '—' }}</td>
              <td>{{ amount(trade.amount == null ? null : String(trade.amount)) }}</td><td>{{ trade.time ?? '—' }}</td>
              <td><button type="button" class="pnl-button" @click="begin(trade)">更正</button></td>
            </tr></tbody>
          </table>
        </div>
        <button v-if="day.next_after" type="button" class="pnl-button" :disabled="loading" @click="load(day.next_after ?? 0)">加载更多记录</button>
        <form v-if="editing" class="pnl-edit" @submit.prevent="saveCorrection">
          <h3>更正记录 {{ editing.id }}</h3>
          <TradeFieldsForm v-model="fields" />
          <label class="pnl-check"><input v-model="keepDistinct" type="checkbox" /> 如有相似记录，确认这是独立一笔</label>
          <div class="pnl-inline">
            <button type="submit" class="pnl-button pnl-primary" :disabled="saving">确认更正</button>
            <button type="button" class="pnl-button" @click="editing = null">取消</button>
          </div>
        </form>
      </section>
      <section class="pnl-panel">
        <h2>收盘持仓与估值</h2>
        <div class="pnl-holdings">
          <div v-for="[title, positions] in ([['上一交易日', day.opening], ['当日', day.closing]] as const)" :key="title">
            <h3>{{ title }}</h3>
            <p v-if="!positions.length" class="pnl-muted">{{ day.issues.length ? '暂无可展示的持仓' : '空仓' }}</p>
            <ul v-else class="pnl-positions">
              <li v-for="position in positions" :key="position.security">
                <strong>{{ position.security }}</strong> · {{ position.quantity }} 股
                <span>{{ position.close == null ? '收盘价待补' : `收盘 ${position.close} · 市值 ${amount(position.value)}` }}</span>
                <span v-if="position.source" class="pnl-muted">{{ position.source }}</span>
              </li>
            </ul>
          </div>
        </div>
        <template v-if="day.available_closes?.length">
          <h3>已取得的当日收盘价</h3>
          <ul class="pnl-positions">
            <li v-for="quote in day.available_closes" :key="quote.security">{{ quote.security }} · {{ quote.close }} · {{ quote.source }}</li>
          </ul>
        </template>
        <h3 v-if="day.actions.length">公司行动</h3>
        <ul v-if="day.actions.length" class="pnl-positions">
          <li v-for="action in day.actions" :key="action.security">{{ action.security }} · 股数变化 {{ action.share_delta }} · 现金调整 {{ currency(action.cash_adjustment) }} · {{ action.source }}</li>
        </ul>
        <h3 v-if="day.executions.length">费用明细</h3>
        <ul v-if="day.executions.length" class="pnl-positions">
          <li v-for="(execution, index) in day.executions" :key="index">
            {{ execution.security }} · {{ execution.side === 'buy' ? '买入' : '卖出' }} {{ execution.quantity }} 股 · 佣金 {{ amount(execution.commission) }}
            <span class="pnl-muted">{{ execution.fee_source === 'confirmed' ? '已核费用' : '模拟佣金万分之 2.5，每笔最低 ¥5' }} · 其他费用 {{ amount(execution.other_fees) }}</span>
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>
