// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import DataCollectionView from './data-collection-view.vue'

let wrapper: VueWrapper | null = null

function dataset(dataset: string, detail?: Record<string, unknown>) {
  return {
    dataset, available: dataset === 'limits', source: 'fixture', observations: dataset === 'limits' ? 64 : 0,
    lastSuccessAt: '2026-09-10T16:00:00+08:00', settled: true, refreshWarning: null,
    latestAttempt: dataset === 'limits' ? {
      taskId: 'task-limits', runId: 'run-1', status: 'failed-retained', source: 'fixture', observations: 64,
      warning: '上次刷新失败，保留旧值', queuedAt: null, startedAt: null, completedAt: null, durationMs: 100, settled: true,
    } : null,
    activeTaskId: null, collectionAllowed: true, restriction: null, coreIndices: [], detail,
  }
}

describe('data collection limits detail', () => {
  afterEach(() => { wrapper?.unmount(); wrapper = null; vi.unstubAllGlobals() })

  it('shows limits sample dates, exclusions and promotion dependency on expansion', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({
      asOf: '2026-09-10', manualRefreshEnabled: true,
      datasets: [dataset('core'), dataset('breadth'), dataset('limits', {
        sampleAsOf: '2026-09-10', previousAsOf: '2026-09-09', excludedCount: 7,
        promotionQuality: 'insufficient', promotionDependency: '需要精确相邻交易日和规范证券身份', warnings: ['缺少收盘状态'],
      }), dataset('sectors'), dataset('activeDirection')],
    }) })))
    wrapper = mount(DataCollectionView)
    await flushPromises()
    await wrapper.find('button[aria-label="展开涨跌停生态"]')
      .trigger('click')
    expect(wrapper.text()).toContain('当前样本日期')
    expect(wrapper.text()).toContain('2026-09-10')
    expect(wrapper.text()).toContain('排除样本数')
    expect(wrapper.text()).toContain('7')
    expect(wrapper.text()).toContain('晋级质量')
    expect(wrapper.text()).toContain('需要精确相邻交易日和规范证券身份')
    expect(wrapper.text()).toContain('缺少收盘状态')
  })
})
