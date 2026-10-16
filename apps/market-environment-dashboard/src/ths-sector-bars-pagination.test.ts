import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchThsSectorBars, type ThsSectorBarsResponse } from './collection-api'
import {
  fetchAllThsSectorBars,
  THS_SECTOR_BARS_PAGE_SIZE,
} from './ths-sector-bars-pagination'
import type { ThsSectorBar } from './types'

vi.mock('./collection-api', () => ({
  fetchThsSectorBars: vi.fn(),
}))

function bar(index: number): ThsSectorBar {
  return {
    tradingDate: `session-${String(index).padStart(4, '0')}`,
    open: index,
    high: index + 1,
    low: index - 1,
    close: index + 0.5,
    volume: index * 10,
    turnover: index * 100,
    quality: 'ok',
    source: 'fixture',
    sourceRevision: 'history-r1',
    warnings: [],
  }
}

function response(page: number, items: ThsSectorBar[]): ThsSectorBarsResponse {
  return {
    thscode: '885001.TI',
    requestedStart: '2022-01-01',
    requestedEnd: '2026-10-12',
    coverage: {
      firstDate: '2022-01-01',
      lastDate: '2026-10-12',
      storedRows: 1001,
      gaps: [],
    },
    items,
    page,
    pageSize: THS_SECTOR_BARS_PAGE_SIZE,
    total: 1001,
  }
}

describe('fetchAllThsSectorBars', () => {
  beforeEach(() => {
    vi.mocked(fetchThsSectorBars).mockReset()
  })

  it('continues exactly two 1000-row pages and stably removes overlap', async () => {
    const firstPage = Array.from({ length: 1000 }, (_, index) => bar(index))
    const finalBar = bar(1000)
    vi.mocked(fetchThsSectorBars)
      .mockResolvedValueOnce(response(1, firstPage))
      .mockResolvedValueOnce(response(2, [firstPage[999], finalBar]))

    const result = await fetchAllThsSectorBars('885001.TI', {
      startDate: '2022-01-01',
      endDate: '2026-10-12',
    })

    expect(fetchThsSectorBars).toHaveBeenCalledTimes(2)
    expect(fetchThsSectorBars).toHaveBeenNthCalledWith(1, '885001.TI', {
      startDate: '2022-01-01',
      endDate: '2026-10-12',
      page: 1,
      pageSize: 1000,
    })
    expect(fetchThsSectorBars).toHaveBeenNthCalledWith(2, '885001.TI', {
      startDate: '2022-01-01',
      endDate: '2026-10-12',
      page: 2,
      pageSize: 1000,
    })
    expect(result.items).toHaveLength(1001)
    expect(new Set(result.items.map((item) => item.tradingDate))).toHaveLength(1001)
    expect(result.items[999]).toEqual(firstPage[999])
    expect(result.items[1000]).toEqual(finalBar)
  })
})
