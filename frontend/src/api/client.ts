import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schemas = components['schemas']
export type Account = Schemas['AccountOut']
export type Category = Schemas['CategoryOut']
export type Txn = Schemas['TxnOut']
export type TxnIn = Schemas['TxnIn']
export type Project = Schemas['ProjectOut']
export type Debt = Schemas['DebtOut']
export type Earmark = Schemas['EarmarkOut']
export type Asset = Schemas['AssetOut']
export type User = Schemas['UserOut']
export type ImportBatch = Schemas['ImportBatchOut']

/** RFC 7807 problem from the API. `code` is machine-readable; `title` is a human message. */
export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown>
  constructor(status: number, body: Record<string, unknown> | null) {
    super((body?.title as string) || `Request failed (${status})`)
    this.status = status
    this.code = (body?.code as string) || 'error'
    this.details = body ?? {}
  }
}

// Access token lives in memory only (Frontend.md §4); the refresh token is an httpOnly cookie.
let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
let onLoggedOut: () => void = () => {}

export function setAccessToken(token: string | null) {
  accessToken = token
}
export function setLoggedOutHandler(fn: () => void) {
  onLoggedOut = fn
}

export async function refreshAccessToken(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const r = await fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'same-origin' })
      if (!r.ok) return false
      const body = await r.json()
      accessToken = body.access_token
      return true
    } catch {
      return false
    } finally {
      setTimeout(() => (refreshing = null), 0)
    }
  })()
  return refreshing
}

const auth: Middleware = {
  async onRequest({ request }) {
    if (accessToken) request.headers.set('Authorization', `Bearer ${accessToken}`)
    return request
  },
}

/** Retry once after refreshing when the access token expired. */
async function fetchWithRefresh(input: Request): Promise<Response> {
  const retry = input.clone()
  const res = await fetch(input)
  if (res.status !== 401 || input.url.includes('/auth/')) return res
  if (await refreshAccessToken()) {
    retry.headers.set('Authorization', `Bearer ${accessToken}`)
    return fetch(retry)
  }
  onLoggedOut()
  return res
}

export const api = createClient<paths>({ baseUrl: '', credentials: 'same-origin', fetch: fetchWithRefresh })
api.use(auth)

/** Unwrap an openapi-fetch result or throw ApiError. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p
  if (!response.ok) throw new ApiError(response.status, (error as Record<string, unknown>) ?? null)
  return data as T
}

/** Plain JSON request for endpoints whose response is untyped (reports) or multipart uploads. */
export async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  const req = new Request(url, { ...init, credentials: 'same-origin' })
  if (accessToken) req.headers.set('Authorization', `Bearer ${accessToken}`)
  const res = await fetchWithRefresh(req)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const json = text ? JSON.parse(text) : null
  if (!res.ok) throw new ApiError(res.status, json)
  return json as T
}

export async function download(url: string, filename: string) {
  const req = new Request(url, { credentials: 'same-origin' })
  if (accessToken) req.headers.set('Authorization', `Bearer ${accessToken}`)
  const res = await fetchWithRefresh(req)
  if (!res.ok) throw new ApiError(res.status, null)
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
