// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TradingPnlCalendar from './TradingPnlCalendar.vue'
import TradingPnlDay from './TradingPnlDay.vue'
import TradingPnlImport from './TradingPnlImport.vue'
import type { Draft } from '../../trading-pnl'

const date = '2026-01-21'
const day = {
  date, status: 'ok', pnl: '0.00', issues: [], previous_date: '2026-01-20', opening: [], closing: [],
  components: { buy_cost: '19621.00' }, executions: [], actions: [], trades: [], next_after: null, coverage: null, revision: 7,
}
const january = { month: '2026-01', opening_date: '2026-01-20', settled_through: '2026-11-27', revision: 7, days: [day] }
const draft: Draft = {
  id: 'draft-test', revision: 7,
  images: [{ digest: 'fixture', hints: ['2026年01月2笔'], rows: [{
    digest: 'fixture', row_number: 0, raw: '合成截图', region: [0, 0.4], issues: [], blocked: false, matches: [],
    fields: { date, security: '603019.SH', name: '测试股票', filled_quantity: 100, side: 'buy', status: 'filled', price: '98.15', amount: '9815.00' },
  }] }],
}

async function page(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/trading-pnl', name: 'trading-pnl-calendar', component: TradingPnlCalendar },
    { path: '/trading-pnl/day/:date', name: 'trading-pnl-day', component: TradingPnlDay },
    { path: '/trading-pnl/import', name: 'trading-pnl-import', component: TradingPnlImport },
  ] })
  await router.push(path)
  const wrapper = mount(defineComponent({ components: { RouterView }, template: '<RouterView />' }), { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

afterEach(() => vi.unstubAllGlobals())

describe('盈亏日历', () => {
  it('区分休市、缺数据和零值，并从明细返回原月份', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/days/')) return response(day)
      const month = url.split('/').at(-1)
      return response({ ...january, month, days: [day,
        { date: '2026-01-22', status: 'insufficient', pnl: null, issues: ['coverage-unconfirmed'] },
        { date: '2026-01-24', status: 'closed', pnl: null, issues: [] },
      ] })
    }))
    const { wrapper, router } = await page('/trading-pnl?month=2026-01')
    expect(wrapper.get('.pnl-calendar').text()).toMatch(/¥0\.00.*待补证据.*休市/)
    await wrapper.get('.pnl-calendar [aria-label="2026-01-21 ¥0.00"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('h1').text()).toContain('2026-01-21')
    expect(wrapper.get('.pnl-total').text()).toBe('¥0.00')
    await wrapper.get('.pnl-back').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/trading-pnl?month=2026-01')
    await wrapper.get('[aria-label="下一月"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.month).toBe('2026-02')
    wrapper.unmount()
  })

  it('修正后重新核对，遇到重复冲突时呈现匹配并只发送一次确认', async () => {
    let confirmCount = 0
    let reviewCount = 0
    let release: (() => void) | undefined
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/drafts')) return response(draft)
      if (url.endsWith('/preview')) {
        reviewCount++
        const next = structuredClone(draft)
        next.images[0].rows[0].fields = JSON.parse(String(options?.body)).rows[0].fields
        if (confirmCount) next.images[0].rows[0].matches = [{ kind: 'possible', id: 42, fields: draft.images[0].rows[0].fields }]
        return response(next)
      }
      confirmCount++
      if (confirmCount === 1) return response({ detail: '台账已更新，请重新核对截图及重复记录' }, 409)
      await new Promise<void>(resolve => { release = resolve })
      return response({ saved: [{ id: 9, date }], skipped: [] })
    }))
    const { wrapper } = await page('/trading-pnl/import?month=2026-01')
    const file = wrapper.get('input[type="file"]')
    Object.defineProperty(file.element, 'files', { value: [new File(['fixture'], 'sample.png', { type: 'image/png' })] })
    await file.trigger('change')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('.pnl-line-preview img').attributes('src')).toContain('/images/fixture')
    await wrapper.get<HTMLInputElement>('.pnl-fields input[type="text"]').setValue('603019.sh')
    expect(wrapper.text()).toContain('字段有修改')
    const button = (label: string) => wrapper.findAll('button').find(item => item.text().includes(label))!
    await button('重新核对').trigger('click')
    await flushPromises()
    expect(reviewCount).toBe(1)
    await button('选择无疑问记录').trigger('click')
    await button('确认本批').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已有相似记录')
    expect(wrapper.get('[role="alert"]').text()).toContain('台账已更新')
    await wrapper.get('.pnl-select-decision select').setValue('keep-distinct')
    await button('确认本批').trigger('click')
    await button('确认本批').trigger('click')
    expect(confirmCount).toBe(2)
    release?.()
    await flushPromises()
    expect(wrapper.text()).toContain('新增 1 笔')
    expect(wrapper.get('a.pnl-back[href*="/day/"]').text()).toBe('核对 2026-01-21 流水')
    wrapper.unmount()
  })

  it('只在提交补齐表单时请求 Fuyao，并列出仍待核对的日期', async () => {
    let finish: (() => void) | undefined
    const fetch = vi.fn(async (url: string, options?: RequestInit) => {
      if (!url.endsWith('/evidence/fuyao')) return response(january)
      expect(options?.method).toBe('POST')
      expect(JSON.parse(String(options?.body))).toEqual({ start: date, end: '2026-01-23', revision: 7 })
      await new Promise<void>(resolve => { finish = resolve })
      return response({
        status: 'partial', revision: 8, added: { sessions: 2, valuations: 1 },
        remaining: [{ date: '2026-01-23', issues: ['coverage-unconfirmed'] }],
        missing_closes: [{ date: '2026-01-23', security: '603019.SH', reason: 'fuyao-history-unavailable' }],
      })
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await page('/trading-pnl?month=2026-01')
    expect(fetch.mock.calls).toHaveLength(1)
    const form = wrapper.get('form[aria-labelledby="pnl-fuyao-title"]')
    const [start, end] = form.findAll<HTMLInputElement>('input')
    expect(start.element.value).toBe(date)
    expect(end.element.value).toBe('2026-01-31')
    await end.setValue('2026-01-23')
    expect(fetch.mock.calls).toHaveLength(1)
    await form.trigger('submit')
    expect(form.text()).toContain('正在补齐…')
    finish?.()
    await flushPromises()
    expect(wrapper.text()).toContain('已补齐部分数据')
    expect(wrapper.text()).toContain('交易流水待确认')
    expect(wrapper.text()).toContain('603019.SH · Fuyao 日线暂不可用')
    expect(wrapper.get('a[href*="/day/2026-01-23"]').text()).toBe('2026-01-23')
    wrapper.unmount()
  })

  it('后续明细可返回导致盈亏待补的日期并确认流水', async () => {
    const blockedDay = '2026-03-20'
    let covered = false
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/coverage')) {
        expect(JSON.parse(String(options?.body))).toEqual({ start: blockedDay, end: blockedDay, kind: 'complete', revision: 7 })
        covered = true
        return response({ revision: 8 })
      }
      if (url.includes(blockedDay)) return response({
        ...day, date: blockedDay, status: covered ? 'ok' : 'insufficient', pnl: covered ? '8.00' : null,
        issues: covered ? [] : ['coverage-unconfirmed'], coverage: covered ? 'complete' : null,
      })
      return response({ ...day, status: 'insufficient', pnl: null, issues: ['prior-holdings-unconfirmed'],
        blocking_coverage_date: blockedDay, coverage: 'no-trades' })
    }))
    const { wrapper, router } = await page('/trading-pnl/day/2026-03-23?month=2026-03')
    await wrapper.get('a[href*="/day/2026-03-20"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.params.date).toBe(blockedDay)
    const button = wrapper.findAll('button').find(item => item.text() === '确认当日流水已录全')!
    await button.trigger('click')
    await flushPromises()
    expect(wrapper.get('.pnl-total').text()).toBe('+¥8.00')
    wrapper.unmount()
  })

  it('跨日更正后提供原日期和新日期的流水核对入口', async () => {
    const target = '2026-01-22'
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/correction')) {
        expect(JSON.parse(String(options?.body)).trade.date).toBe(target)
        return response({ revision: 8, affected_dates: [date, target] })
      }
      return response({
        ...day, trades: url.includes(target) ? [] : [{ ...draft.images[0].rows[0].fields, id: 4, revision: 7 }],
      })
    }))
    const { wrapper, router } = await page('/trading-pnl/day/2026-01-21?month=2026-01')
    await wrapper.findAll('button').find(item => item.text() === '更正')!.trigger('click')
    await wrapper.get<HTMLInputElement>('.pnl-edit input[type="date"]').setValue(target)
    await wrapper.get('.pnl-edit').trigger('submit')
    await flushPromises()
    expect(router.currentRoute.value.params.date).toBe(target)
    const links = wrapper.get('nav[aria-label="需要重新确认的日期"]').findAll('a')
    expect(links.map(link => link.text())).toEqual(['核对 2026-01-21 流水', '核对 2026-01-22 流水'])
    wrapper.unmount()
  })
})
