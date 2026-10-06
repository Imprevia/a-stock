// @vitest-environment happy-dom


vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))
import { setActivePinia, createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document05SectorsPage from './Document05SectorsPage.vue'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'

function makeResponse(withRows: boolean, sectorEnrichment?: Record<string, unknown>) {
  return {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'degraded',
      coverage: 0.5,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
      sectors: withRows
        ? {
            state: '轮动加速',
            rows: [
              { code: 'ai', name: '人工智能', changePct: 2.35, upCount: 120, downCount: 30, mainNet: 1500000000, leader: '某AI股' },
              { code: 'semi', name: '半导体', changePct: -1.2, upCount: 40, downCount: 110, mainNet: -300000000, leader: null },
            ],
            quality: { dataset: 'industry-ranking', source: 'fixture', provider: 'fixture', status: 'ok', observations: 86, asOf: '2026-09-03', warnings: [], ...(sectorEnrichment ? { sectorEnrichment } : {}) },
          }
        : {
            state: 'insufficient',
            rows: [],
            quality: { dataset: 'industry-ranking', source: 'fixture', provider: 'fixture', status: 'missing', observations: 0, asOf: '2026-09-03', warning: '行业排名未返回', warnings: [], ...(sectorEnrichment ? { sectorEnrichment } : {}) },
          },
    },
  }
}

async function mountPage(withRows: boolean, sectorEnrichment?: Record<string, unknown>) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse(withRows, sectorEnrichment) as never
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/05')
  await router.isReady()
  const wrapper = mount(Document05SectorsPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('Document05SectorsPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the sector table rows with tone classes', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.text()).toContain('轮动加速')
    expect(wrapper.text()).toContain('人工智能')
    expect(wrapper.text()).toContain('半导体')
    expect(wrapper.text()).toContain('+2.35%')
    expect(wrapper.text()).toContain('-1.20%')
    expect(wrapper.text()).toContain('某AI股')
    expect(wrapper.text()).toContain('15.0 亿')
    expect(wrapper.text()).toContain('-3.0 亿')
  })

  it('renders the empty fallback when sectors has no rows', async () => {
    const wrapper = await mountPage(false)
    expect(wrapper.text()).toContain('板块数据不足')
    expect(wrapper.text()).toContain('行业排名未返回')
  })

  it('renders the default fallback text when warning is absent', async () => {
    setActivePinia(createPinia())
    const market = useMarketStore()
    const response = makeResponse(false) as { chapter01: { sectors: { quality: Record<string, unknown> } } }
    delete response.chapter01.sectors.quality.warning
    market.data = response as never
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/dashboard/05')
    await router.isReady()
    const wrapper = mount(Document05SectorsPage, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('行业相对强度、成交持续性、板块宽度和集中度尚未返回。')
  })

  it('keeps empty sectors explicit when supplemental enrichment is present', async () => {
    const wrapper = await mountPage(false, {
      status: 'base-only',
      source: 'eastmoney-dataapi',
      sameVendor: true,
      matchedRows: 0,
      unmatchedRows: 320,
      identityCoverage: 0,
      warnings: ['同供应商字段补充未匹配，保留基础行业结果'],
    })

    expect(wrapper.text()).toContain('字段补充 · 仅基础结果')
    expect(wrapper.text()).toContain('同供应商字段补充：东方财富 dataapi')
    expect(wrapper.text()).toContain('身份匹配 0%')
    expect(wrapper.text()).toContain('同供应商字段补充未匹配')
    expect(wrapper.text()).toContain('板块数据不足')
  })

  it('shows partial enrichment coverage and latest-only warning beside base rows', async () => {
    const wrapper = await mountPage(true, {
      status: 'partial',
      source: 'eastmoney-dataapi',
      sameVendor: true,
      mappingRevision: 'ths-eastmoney-v1',
      matchedRows: 1,
      unmatchedRows: 1,
      identityCoverage: 0.5,
      fieldCoverage: { mainNet: 1, mainNetPct: 0.5, upCount: 1, downCount: 0, leader: 0 },
      dateEvidence: { reason: '仅当前上海交易日补充' },
      warnings: ['未匹配行业字段保持空值'],
    })

    expect(wrapper.text()).toContain('字段补充 · 部分补充')
    expect(wrapper.text()).toContain('身份匹配 50%')
    expect(wrapper.text()).toContain('匹配 1 行 · 未匹配 1 行')
    expect(wrapper.text()).toContain('字段覆盖：主力净额 100%、主力净额比例 50%、上涨家数 100%、下跌家数 0%、领涨股 0%')
    expect(wrapper.text()).toContain('映射版本 ths-eastmoney-v1')
    expect(wrapper.text()).toContain('仅当前上海交易日补充')
    expect(wrapper.text()).toContain('未匹配行业字段保持空值')
  })
})
