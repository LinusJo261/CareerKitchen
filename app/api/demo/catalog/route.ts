import { backendFor } from '@/lib/server/backend'
import { errorResponse, GatewayError } from '@/lib/server/http-utils'

export async function GET(request: Request) {
  try {
    const api = await backendFor(request)
    if (api.mode !== 'sample')
      throw new GatewayError(
        403,
        'DEMO_ONLY',
        'Enter demo mode to browse the sample market.',
      )
    const input = new URL(request.url).searchParams
    const params = new URLSearchParams({
      kind: input.get('kind') === 'applicants' ? 'applicants' : 'jobs',
      q: (input.get('q') || '').slice(0, 100),
      offset: input.get('offset') || '0',
      limit: '24',
    })
    const result = await api.request('/v1/demo/catalog?' + params)
    return Response.json(result, { headers: { 'Cache-Control': 'no-store' } })
  } catch (error) {
    return errorResponse(error)
  }
}
