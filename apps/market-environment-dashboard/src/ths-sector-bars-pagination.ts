import {
  fetchThsSectorBars,
  type ThsSectorBarsQuery,
  type ThsSectorBarsResponse,
} from './collection-api'
import type { ThsSectorBar } from './types'

export const THS_SECTOR_BARS_PAGE_SIZE = 1000

type ThsSectorBarsRangeQuery = Pick<ThsSectorBarsQuery, 'startDate' | 'endDate'>

function barIdentity(thscode: string, bar: ThsSectorBar): string {
  return `${bar.thscode || thscode}:${bar.tradingDate}`
}

function mergeUniqueBars(
  thscode: string,
  pages: ThsSectorBarsResponse[],
): ThsSectorBar[] {
  const seen = new Set<string>()
  const merged: ThsSectorBar[] = []
  for (const page of pages) {
    for (const bar of page.items) {
      const identity = barIdentity(thscode, bar)
      if (seen.has(identity)) continue
      seen.add(identity)
      merged.push(bar)
    }
  }
  return merged
}

/** Read every bounded legacy THS bars page while preserving server order. */
export async function fetchAllThsSectorBars(
  thscode: string,
  query: ThsSectorBarsRangeQuery = {},
): Promise<ThsSectorBarsResponse> {
  const first = await fetchThsSectorBars(thscode, {
    ...query,
    page: 1,
    pageSize: THS_SECTOR_BARS_PAGE_SIZE,
  })
  const pages = [first]
  const pageCount = Math.ceil(first.total / THS_SECTOR_BARS_PAGE_SIZE)

  for (let page = 2; page <= pageCount; page += 1) {
    pages.push(await fetchThsSectorBars(thscode, {
      ...query,
      page,
      pageSize: THS_SECTOR_BARS_PAGE_SIZE,
    }))
  }

  return {
    ...first,
    items: mergeUniqueBars(first.thscode, pages),
    page: 1,
    pageSize: THS_SECTOR_BARS_PAGE_SIZE,
  }
}
