export type TradeFields = Record<string, string | number | boolean | null>
export type LedgerStatus = 'ok' | 'estimated' | 'closed' | 'setup' | 'before-start' | 'future' | 'insufficient'
export type Decision = 'add' | 'skip' | 'keep-distinct'

export interface DaySummary {
  date: string
  status: LedgerStatus
  pnl: string | null
  estimated_pnl?: string | null
  issues: string[]
  blocking_coverage_date?: string | null
  blocking_holdings_date?: string | null
  blocking_holdings_issues?: string[]
}

export interface ImportedTrade {
  id: number
  date: string
  security: string
  name: string | null
  side: string
  quantity: number
  price: string | null
}

export interface ImportResult {
  batch_id: string | null
  imported: ImportedTrade[]
  skipped: unknown[]
}

export interface CalculationResult {
  status: 'running' | 'complete' | 'partial' | 'waiting-settlement' | 'retry'
  start: string
  end: string | null
  missing: { date: string; security?: string; reason: string }[]
  revision: number
}

export function calculationRequest(batch: string, method: 'GET' | 'POST' = 'GET'): Promise<CalculationResult> {
  return ledgerRequest(`/calculations/${encodeURIComponent(batch)}`, method === 'POST' ? {} : undefined)
}

export function calculationQuery(query: Record<string, unknown>): { batch?: string; start?: string; end?: string } {
  const { batch, start, end } = query
  const isDate = (value: unknown): value is string => typeof value === 'string' && /^20\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(value)
  return {
    ...(typeof batch === 'string' && batch ? { batch } : {}),
    ...(isDate(start) && isDate(end) && start <= end ? { start, end } : {}),
  }
}

export function dayPnl(day: DaySummary): string | null {
  if (day.status === 'estimated') return day.estimated_pnl ?? null
  return day.status === 'ok' ? day.pnl : null
}

export function dayPnlLabel(day: DaySummary): string {
  const value = dayPnl(day)
  if (value == null) return statusText[day.status]
  return day.status === 'estimated' ? `估算 ${currency(value)}` : currency(value)
}

export interface LedgerMonth {
  month: string
  days: DaySummary[]
  revision: number
  opening_date: string | null
  settled_through: string
}

export interface MarketBackfillResult {
  revision: number
  status: 'complete' | 'partial' | 'insufficient'
  added: { sessions: number; valuations: number }
  remaining: { date: string; issues: string[] }[]
  missing_closes: { date: string; security: string; reason: string }[]
}

export interface Position {
  security: string
  quantity: number
  close: string | null
  value: string | null
  source: string | null
}

export type LedgerRecord = TradeFields & { id: number; revision: number }

export interface LedgerDay extends DaySummary {
  previous_date: string | null
  opening: Position[]
  closing: Position[]
  available_closes: { security: string; close: string; source: string }[]
  components: Record<string, string | null> | null
  executions: { security: string; side: string; quantity: number; commission: string; other_fees: string; fee_source: string }[]
  actions: { security: string; share_delta: number; cash_adjustment: string; source: string }[]
  trades: LedgerRecord[]
  next_after: number | null
  coverage: 'complete' | 'no-trades' | null
  revision: number
}

export interface DraftRow {
  digest: string
  row_number: number
  fields: TradeFields
  raw: string
  region: [number, number]
  issues: string[]
  blocked: boolean
  matches: { kind: string; id?: number; row_number?: number; fields: TradeFields }[]
}

export interface Draft {
  id: string
  revision: number
  images: { digest: string; hints: string[]; rows: DraftRow[] }[]
}

export const LEDGER_API = '/api/trading-pnl'

export class LedgerError extends Error {
  constructor(message: string, public readonly status: number, public readonly detail?: {
    added?: MarketBackfillResult['added']
  }) {
    super(message)
  }
}

export async function ledgerRequest<T>(path: string, body?: unknown): Promise<T> {
  const form = body instanceof FormData
  const response = await fetch(`${LEDGER_API}${path}`, body === undefined ? {} : {
    method: 'POST',
    headers: form ? undefined : { 'Content-Type': 'application/json' },
    body: form ? body : JSON.stringify(body),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload?.detail
    const reason = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((item: { msg: string }) => item.msg).join('，')
      : detail?.message
    throw new LedgerError(reason || '请求失败，请重试', response.status, detail)
  }
  return payload as T
}

export function shanghaiDate(): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
}

export function currency(value: string | null | undefined): string {
  if (value == null) return '—'
  const formatted = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(Number(value))
  return Number(value) > 0 ? `+${formatted}` : formatted
}

export function amount(value: string | null | undefined): string {
  if (value == null) return '—'
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(Number(value))
}

export function statusLabel(status: string): string {
  return ({ filled: '全部成交', partial: '部分成交', pending: '未成交委托', canceled: '撤单' } as Record<string, string>)[status] ?? status
}

export function issueLabel(issue: string): string {
  const [key, first, second] = issue.split(':')
  const label = ({
    'opening-required': '请先确认期初持仓', 'coverage-unconfirmed': '交易流水待确认',
    'calendar-missing': '交易日历待补', 'prior-holdings-unconfirmed': '上一交易日持仓待核对',
    'fees-unconfirmed': '费用待核对', 'missing-actions': first ? `${first} 公司行动待核对` : '公司行动待核对',
    'missing-close': [...[first, second].filter(Boolean), '缺收盘价'].join(' '),
    'negative-position': first ? `${first} 持仓数量异常` : '持仓数量异常',
    'order-conflict': `委托 ${first} 的成交记录有冲突`,
    'coverage-blocked': `${first} 的交易流水待确认`,
    'calendar-chain-gap': `截至 ${first} 的持仓缺少连续交易日历`,
    'fuyao-calendar-coverage': '缺少可核实的 Fuyao 交易日关系',
    'fuyao-calendar-unavailable': 'Fuyao 交易日历暂不可用',
    'fuyao-invalid-calendar': 'Fuyao 交易日历未通过校验',
    'fuyao-close-missing': 'Fuyao 缺可用的不复权收盘价',
    'fuyao-history-unavailable': 'Fuyao 日线暂不可用',
    'fuyao-history-rejected': 'Fuyao 拒绝日线请求',
    'fuyao-history-permission': 'Fuyao 日线凭据或权限有问题',
    'fuyao-history-rate-limited': 'Fuyao 日线请求受限，请稍后重试',
    'fuyao-invalid-history': 'Fuyao 日线未通过校验',
    'fuyao-batch-limit': '本轮补齐达到上限，剩余数据可重试',
    'fuyao-action-coverage-unknown': 'Fuyao 公司行动覆盖待核验',
    'fuyao-action-entitlement-unverified': '公司行动的实际权益待核验',
    'fuyao-conflicting-action': 'Fuyao 公司行动记录存在冲突',
    'fuyao-invalid-actions': 'Fuyao 公司行动未通过校验',
    'fuyao-actions-unavailable': 'Fuyao 公司行动暂不可用',
    'fuyao-actions-rejected': 'Fuyao 拒绝公司行动请求',
    'fuyao-actions-permission': 'Fuyao 公司行动凭据或权限有问题',
    'fuyao-actions-rate-limited': 'Fuyao 公司行动请求受限，请稍后重试',
    'fuyao-actions-batch-limit': '本轮已达公司行动查询上限，剩余数据可重试',
  } as Record<string, string>)[key]
  if (!label) return issue
  return first && /^fuyao-.*action/.test(key) ? `${first} ${label}` : label
}

export function dayIssueLabels(day: DaySummary): string[] {
  const issues = day.issues.map(issueLabel)
  if (day.blocking_coverage_date && day.blocking_coverage_date < day.date) {
    issues.push(issueLabel(`coverage-blocked:${day.blocking_coverage_date}`))
  }
  if (day.blocking_holdings_date && day.blocking_holdings_date < day.date) {
    for (const issue of day.blocking_holdings_issues ?? []) {
      issues.push(`${day.blocking_holdings_date} · ${issueLabel(issue)}`)
    }
  }
  return [...new Set(issues)]
}

export const statusText: Record<LedgerStatus, string> = {
  ok: '已计算', estimated: '估算', closed: '休市', setup: '待初始化', 'before-start': '起始日前', future: '未到日期', insufficient: '待补证据',
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请重试'
}
