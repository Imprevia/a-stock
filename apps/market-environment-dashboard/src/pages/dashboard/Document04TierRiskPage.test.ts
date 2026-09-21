// @vitest-environment happy-dom

import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Document04TierRiskPage from './Document04TierRiskPage.vue'
import { useMarketStore } from '../../stores/market'

const baseChapter = {
  status: 'degraded',
  coverage: 0.4,
  combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
  assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
}

const quality = (status: string, reason: string) => ({
  status,
  reason,
  observations: 1,
  asOf: '2026-09-03',
  source: 'fixture',
  warnings: [],
})

function makeLimits(mode: 'complete' | 'partial' | 'empty') {
  if (mode === 'empty') return undefined
  return {
    limitUpCount: 10,
    limitDownCount: 2,
    failedLimitUpCount: 3,
    failedLimitUpRatio: 0.23,
    maxStreak: 4,
    state: 'fixture',
    quality: { dataset: 'limits', source: 'fixture', status: 'ok', observations: 10 },
    stratifications: [
      { dimension: 'risk_tier', key: 'high', label: '高位', count: 6, quality: quality('ok', '高位样本可用') },
      ...(mode === 'complete' ? [
        { dimension: 'risk_tier', key: 'middle', label: '中位', count: 12, quality: quality('degraded', '中位样本降级') },
        { dimension: 'risk_tier', key: 'low', label: '低位', count: 4, quality: quality('insufficient', '低位样本不足') },
      ] : []),
    ],
    riskEvidence: mode === 'complete'
      ? [{ code: 'failure-repair', label: '炸板修复', value: 0.35, evidence: ['15 个炸板样本中 5 个修复'], quality: quality('ok', '修复样本可用') }]
      : [],
  }
}

function mountPage(mode: 'complete' | 'partial' | 'empty') {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: { ...baseChapter, limits: makeLimits(mode) },
  } as never
  return mount(Document04TierRiskPage)
}

describe('Document04TierRiskPage', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => vi.unstubAllGlobals())

  it('从 limits 展示三层样本、修复率和各自质量', () => {
    const wrapper = mountPage('complete')
    expect(wrapper.text()).toContain('高位样本6')
    expect(wrapper.text()).toContain('中位样本12')
    expect(wrapper.text()).toContain('低位样本4')
    expect(wrapper.text()).toContain('炸板修复率35%')
    expect(wrapper.text()).toContain('中位样本降级')
    expect(wrapper.text()).toContain('低位样本不足')
    expect(wrapper.text()).toContain('15 个炸板样本中 5 个修复')
    expect(wrapper.text()).not.toContain('分层样本必须独立计算')
  })

  it('单项缺失时保留其他真实证据', () => {
    const wrapper = mountPage('partial')
    expect(wrapper.text()).toContain('高位样本6')
    expect(wrapper.text()).toContain('中位样本--')
    expect(wrapper.text()).toContain('炸板修复率--')
    expect(wrapper.text()).toContain('高位样本可用')
    expect(wrapper.text()).not.toContain('分层样本必须独立计算')
  })

  it('全部证据缺失时明确展示不足状态', () => {
    const wrapper = mountPage('empty')
    expect(wrapper.text()).toContain('高位样本--')
    expect(wrapper.text()).toContain('数据不足')
    expect(wrapper.text()).toContain('分层样本必须独立计算')
    expect(wrapper.text()).toContain('不按安全状态处理')
  })
})
