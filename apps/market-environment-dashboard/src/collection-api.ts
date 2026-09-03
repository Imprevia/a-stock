export type CollectionDataset = 'core' | 'breadth' | 'limits' | 'sectors' | 'activeDirection'
export type CollectionRunStatus = 'queued' | 'collecting' | 'success' | 'partial' | 'failed'
export type CollectionTaskStatus = 'queued' | 'collecting' | 'success' | 'partial' | 'failed-retained' | 'failed-missing' | 'busy'

export interface CoreIndexCollectionResult {
  code: string
  name: string
  status: CollectionTaskStatus
  source: string
  observations: number
  warning: string | null
  durationMs: number | null
}

export interface CollectionAttempt {
  taskId: string
  runId: string
  status: CollectionTaskStatus
  source: string
  observations: number
  warning: string | null
  queuedAt: string | null
  startedAt: string | null
  completedAt: string | null
  durationMs: number | null
  settled: boolean
}

export interface DatasetCollectionStatus {
  dataset: CollectionDataset
  available: boolean
  source: string
  observations: number
  lastSuccessAt: string | null
  settled: boolean
  refreshWarning: string | null
  latestAttempt: CollectionAttempt | null
  activeTaskId: string | null
  collectionAllowed: boolean
  restriction: string | null
  coreIndices: CoreIndexCollectionResult[]
}

export interface CollectionStatusResponse {
  asOf: string
  manualRefreshEnabled: boolean
  datasets: DatasetCollectionStatus[]
}

export interface CollectionTask extends Omit<CollectionAttempt, 'runId'> {
  dataset: CollectionDataset
  asOf: string
  timings: Record<string, number>
  coreIndices: CoreIndexCollectionResult[]
}

export interface CollectionRun {
  runId: string
  asOf: string
  status: CollectionRunStatus
  requestedDatasets: CollectionDataset[]
  completedTasks: number
  totalTasks: number
  createdAt: string
  startedAt: string | null
  completedAt: string | null
  tasks: CollectionTask[]
}

export async function fetchCollectionStatus(asOf?: string): Promise<CollectionStatusResponse> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''
  return requestJson(`/api/market-environment/data-collection${query}`)
}

export async function startCollectionRun(
  asOf: string,
  datasets?: CollectionDataset[],
): Promise<CollectionRun> {
  return requestJson('/api/market-environment/collection-runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asOf, ...(datasets ? { datasets } : {}) }),
  })
}

export async function fetchCollectionRun(runId: string): Promise<CollectionRun> {
  return requestJson(`/api/market-environment/collection-runs/${encodeURIComponent(runId)}`)
}

export async function pollCollectionRun(
  runId: string,
  options: { intervalMs?: number; isCurrent?: () => boolean } = {},
): Promise<CollectionRun | null> {
  const intervalMs = options.intervalMs ?? 600
  while (options.isCurrent?.() !== false) {
    const run = await fetchCollectionRun(runId)
    if (options.isCurrent?.() === false) return null
    if (!['queued', 'collecting'].includes(run.status)) return run
    await new Promise((resolve) => globalThis.setTimeout(resolve, intervalMs))
  }
  return null
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}
