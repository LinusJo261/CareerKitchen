import 'server-only'
import { apiBase, GatewayError } from './http-utils'
import { sampleApiBase, sessionConnection } from './session'

export type ApiEnvelope<T> = {
  data: T
  capacity?: { used: number; maximum: number }
  page?: { has_more: boolean; next_cursor: string | null }
}
export class Backend {
  constructor(
    private token: string,
    public readonly mode: 'sample' | 'standard' = 'standard',
  ) {}
  async request<T>(
    path: string,
    options: { method?: string; body?: unknown; key?: string } = {},
  ): Promise<ApiEnvelope<T>> {
    if (!path.startsWith('/v1/') || path.includes('://') || path.includes('..'))
      throw new GatewayError(422, 'INVALID_PATH', 'Invalid API route.')
    const base =
      this.mode === 'sample'
        ? sampleApiBase()
        : apiBase(
            process.env.CAREER_KITCHEN_API_URL,
            process.env.NODE_ENV !== 'production',
          )
    const method = options.method || 'GET'
    const multipart = options.body instanceof FormData
    let response: Response
    try {
      response = await fetch(base + path, {
        method,
        headers: {
          Authorization: `Bearer ${this.token}`,
          ...(options.body !== undefined && !multipart
            ? { 'Content-Type': 'application/json' }
            : {}),
          ...(options.key ? { 'Idempotency-Key': options.key } : {}),
        },
        ...(options.body !== undefined
          ? {
              body: multipart
                ? (options.body as FormData)
                : JSON.stringify(options.body),
            }
          : {}),
        cache: 'no-store',
        redirect: 'error',
        signal: AbortSignal.timeout(
          this.mode === 'sample' && path === '/v1/demo/reconcile'
            ? 45000
            : 15000,
        ),
      })
    } catch {
      throw new GatewayError(
        503,
        'API_UNAVAILABLE',
        'The backend is unavailable. Your change has not been confirmed.',
      )
    }
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      const fields = payload?.error?.fields
        ?.map((field: { field: string }) => field.field)
        .join(', ')
      throw new GatewayError(
        response.status,
        payload?.error?.code || 'API_ERROR',
        (payload?.error?.message || 'The API request failed.') +
          (fields ? ` Check: ${fields}.` : ''),
      )
    }
    return payload as ApiEnvelope<T>
  }
  async get<T>(path: string) {
    return (await this.request<T>(path)).data
  }
  async optional<T>(path: string, fallback: T, allowed = [403, 404]) {
    try {
      return await this.get<T>(path)
    } catch (error) {
      if (error instanceof GatewayError && allowed.includes(error.status))
        return fallback
      throw error
    }
  }
  async all<T>(path: string): Promise<T[]> {
    const rows: T[] = []
    let cursor: string | null = null
    for (let page = 0; page < 10; page++) {
      const result: ApiEnvelope<T[]> = await this.request<T[]>(
        path +
          (path.includes('?') ? '&' : '?') +
          'limit=100' +
          (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''),
      )
      rows.push(...result.data)
      if (!result.page?.has_more || !result.page.next_cursor) return rows
      cursor = result.page.next_cursor
    }
    throw new GatewayError(
      503,
      'PAGE_LIMIT',
      'This workspace is too large to load. Contact support.',
    )
  }
}
export async function backendFor(request: Request) {
  const connection = await sessionConnection(request)
  return new Backend(connection.token, connection.mode)
}
