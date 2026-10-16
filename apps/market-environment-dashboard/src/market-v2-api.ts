export type V2QualityStatus =
  | 'ok'
  | 'partial'
  | 'fallback'
  | 'fallback-derived'
  | 'missing'
  | 'insufficient'
  | 'degraded'
  | 'failed'
  | 'failed-retained'
  | 'failed-missing'
  | 'unverified'

export interface V2Quality {
  status: V2QualityStatus
  source?: string | null
  provider?: string | null
  actualDate?: string | null
  observations?: number | null
  cacheState?: 'fresh' | 'stale' | 'missing' | null
  isStale?: boolean | null
  fetchedAt?: string | null
  evidenceRevision?: string | null
  checksum?: string | null
  warnings: string[]
}

export interface V2Link {
  relation: string
  href: string
  resource: string
  method: 'GET'
  title?: string | null
  templated?: boolean
}

export interface V2Envelope<T> {
  asOf: string
  generatedAt: string
  snapshotRevision: string
  quality: V2Quality
  data: T
  links: V2Link[]
}

export interface V2Pagination {
  limit: number
  returned: number
  hasMore: boolean
  nextCursor: string | null
}

export interface V2PaginatedEnvelope<T> extends V2Envelope<T> {
  pagination: V2Pagination
}

export interface V2CollectionData<T> {
  items: T[]
}

export interface V2ErrorPayload {
  code: string
  message: string
  parameter?: string | null
  requestedSnapshotRevision?: string | null
  currentSnapshotRevision?: string | null
}

export class V2ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly parameter: string | null
  readonly requestedSnapshotRevision: string | null
  readonly currentSnapshotRevision: string | null

  constructor(status: number, payload: V2ErrorPayload) {
    super(payload.message)
    this.name = 'V2ApiError'
    this.status = status
    this.code = payload.code
    this.parameter = payload.parameter ?? null
    this.requestedSnapshotRevision = payload.requestedSnapshotRevision ?? null
    this.currentSnapshotRevision = payload.currentSnapshotRevision ?? null
  }
}

export class V2NotFoundError extends V2ApiError {
  constructor(payload: V2ErrorPayload) {
    super(404, payload)
    this.name = 'V2NotFoundError'
  }
}

export class V2RevisionConflictError extends V2ApiError {
  constructor(payload: V2ErrorPayload) {
    super(409, payload)
    this.name = 'V2RevisionConflictError'
  }
}

export type V2ApiResult<T> =
  | { status: 'ok'; envelope: T; etag: string | null }
  | { status: 'not-modified'; snapshotRevision: string | null }

export interface V2RequestOptions {
  snapshotRevision?: string
  ifNoneMatch?: string
  signal?: AbortSignal
  fetcher?: typeof fetch
}

export interface V2CollectedPages<T> {
  items: T[]
  snapshotRevision: string
  pageCount: number
  quality: V2Quality | null
  generatedAt: string | null
}

export interface V2CollectionRestartResult<T, TOverview> extends V2CollectedPages<T> {
  overview: V2Envelope<TOverview> | null
  restarted: boolean
}

function etagValue(value: string | null): string | null {
  if (!value) return null
  const normalized = value.trim().replace(/^W\//, '')
  if (normalized.length >= 2 && normalized.startsWith('"') && normalized.endsWith('"')) {
    return normalized.slice(1, -1)
  }
  return normalized || null
}

function quotedEtag(value: string): string {
  if (!value || /["\r\n]/.test(value)) throw new Error('无效的 snapshot revision')
  return `"${value}"`
}

function errorPayload(status: number, body: unknown): V2ErrorPayload {
  const root = body && typeof body === 'object' ? body as Record<string, unknown> : {}
  const nested = root.error && typeof root.error === 'object'
    ? root.error as Record<string, unknown>
    : root.detail && typeof root.detail === 'object'
      ? root.detail as Record<string, unknown>
      : root
  const detail = typeof root.detail === 'string' ? root.detail : null
  return {
    code: typeof nested.code === 'string' ? nested.code : `http_${status}`,
    message: typeof nested.message === 'string' ? nested.message : detail ?? `请求失败（${status}）`,
    parameter: typeof nested.parameter === 'string' ? nested.parameter : null,
    requestedSnapshotRevision: typeof nested.requestedSnapshotRevision === 'string'
      ? nested.requestedSnapshotRevision
      : null,
    currentSnapshotRevision: typeof nested.currentSnapshotRevision === 'string'
      ? nested.currentSnapshotRevision
      : null,
  }
}

async function responseBody(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function apiError(status: number, payload: V2ErrorPayload): V2ApiError {
  if (status === 404) return new V2NotFoundError(payload)
  if (status === 409) return new V2RevisionConflictError(payload)
  return new V2ApiError(status, payload)
}

export async function requestV2<T>(
  path: string,
  options: V2RequestOptions = {},
): Promise<V2ApiResult<T>> {
  const headers = new Headers()
  if (options.snapshotRevision) headers.set('If-Match', quotedEtag(options.snapshotRevision))
  if (options.ifNoneMatch) headers.set('If-None-Match', quotedEtag(options.ifNoneMatch))
  const response = await (options.fetcher ?? fetch)(path, {
    method: 'GET',
    headers,
    signal: options.signal,
  })
  const etag = etagValue(response.headers.get('ETag'))
  if (response.status === 304) {
    return { status: 'not-modified', snapshotRevision: etag }
  }
  if (!response.ok) {
    throw apiError(response.status, errorPayload(response.status, await responseBody(response)))
  }
  return {
    status: 'ok',
    envelope: await response.json() as T,
    etag,
  }
}

export function marketV2OverviewPath(asOf: string): string {
  return `/api/v2/market-environment/${encodeURIComponent(asOf)}/overview`
}

export async function fetchV2Overview<T>(
  asOf: string,
  options: V2RequestOptions = {},
): Promise<V2ApiResult<V2Envelope<T>>> {
  return requestV2(marketV2OverviewPath(asOf), options)
}

function cursorPath(path: string, cursor: string): string {
  const url = new URL(path, 'http://market-v2.local')
  url.searchParams.set('cursor', cursor)
  return `${url.pathname}${url.search}`
}

export async function fetchAllV2Pages<T>(
  path: string,
  snapshotRevision: string,
  identity: (item: T) => string,
  options: Omit<V2RequestOptions, 'snapshotRevision'> = {},
): Promise<V2CollectedPages<T>> {
  const items: T[] = []
  const identities = new Set<string>()
  const cursors = new Set<string>()
  let nextPath = path
  let pageCount = 0
  let quality: V2Quality | null = null
  let generatedAt: string | null = null

  while (true) {
    const result = await requestV2<V2PaginatedEnvelope<V2CollectionData<T>>>(nextPath, {
      ...options,
      snapshotRevision,
    })
    if (result.status === 'not-modified') {
      throw new V2ApiError(304, {
        code: 'unexpected_not_modified',
        message: '分页读取不接受 304 响应',
      })
    }
    if (result.envelope.snapshotRevision !== snapshotRevision) {
      throw new V2RevisionConflictError({
        code: 'snapshot_revision_conflict',
        message: '分页响应版本与固定版本不一致',
        requestedSnapshotRevision: snapshotRevision,
        currentSnapshotRevision: result.envelope.snapshotRevision,
      })
    }
    pageCount += 1
    quality ??= result.envelope.quality
    generatedAt ??= result.envelope.generatedAt
    for (const item of result.envelope.data.items) {
      const key = identity(item)
      if (identities.has(key)) continue
      identities.add(key)
      items.push(item)
    }
    const pagination = result.envelope.pagination
    if (!pagination.hasMore) break
    if (!pagination.nextCursor || cursors.has(pagination.nextCursor)) {
      throw new V2ApiError(500, {
        code: 'invalid_pagination_continuation',
        message: '分页响应缺少有效的后续 cursor',
      })
    }
    cursors.add(pagination.nextCursor)
    nextPath = cursorPath(path, pagination.nextCursor)
  }

  return { items, snapshotRevision, pageCount, quality, generatedAt }
}

export async function fetchV2CollectionWithOverviewRestart<T, TOverview>(args: {
  asOf: string
  path: string
  snapshotRevision: string
  identity: (item: T) => string
  fetcher?: typeof fetch
  signal?: AbortSignal
}): Promise<V2CollectionRestartResult<T, TOverview>> {
  const options = { fetcher: args.fetcher, signal: args.signal }
  try {
    return {
      ...await fetchAllV2Pages(args.path, args.snapshotRevision, args.identity, options),
      overview: null,
      restarted: false,
    }
  } catch (cause) {
    if (!(cause instanceof V2RevisionConflictError)) throw cause
    const overviewResult = await fetchV2Overview<TOverview>(args.asOf, options)
    if (overviewResult.status === 'not-modified') {
      throw new V2ApiError(304, {
        code: 'unexpected_not_modified',
        message: '重新读取 overview 时收到意外的 304 响应',
      })
    }
    const revision = overviewResult.envelope.snapshotRevision
    return {
      ...await fetchAllV2Pages(args.path, revision, args.identity, options),
      overview: overviewResult.envelope,
      restarted: true,
    }
  }
}
