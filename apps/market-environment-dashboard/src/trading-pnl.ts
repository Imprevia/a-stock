export type TradeFields = Record<string, string | number | boolean | null>
export type LedgerStatus = 'ok' | 'closed' | 'setup' | 'before-start' | 'future' | 'insufficient'
export type Decision = 'add' | 'skip' | 'keep-distinct'

export interface DaySummary {
  date: string
  status: LedgerStatus
  pnl: string | null
  issues: string[]
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
  blocking_coverage_date?: string | null
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
  return ({
    'opening-required': '请先确认期初持仓', 'coverage-unconfirmed': '交易流水待确认',
    'calendar-missing': '交易日历待补', 'prior-holdings-unconfirmed': '上一交易日持仓待核对',
    'fees-unconfirmed': '费用待核对', 'missing-actions': `${first} 公司行动待核对`,
    'missing-close': `${first} ${second} 缺收盘价`, 'negative-position': `${first} 持仓数量异常`,
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
  } as Record<string, string>)[key] ?? issue
}

export const statusText: Record<LedgerStatus, string> = {
  ok: '已计算', closed: '休市', setup: '待初始化', 'before-start': '起始日前', future: '未到日期', insufficient: '待补证据',
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请重试'
}
