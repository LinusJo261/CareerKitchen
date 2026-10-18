import { backendFor } from '@/lib/server/backend'
import {
  assertSameOrigin,
  errorResponse,
  GatewayError,
  operationKey,
} from '@/lib/server/http-utils'
import { workspaceCommand } from '@/lib/server/workspace-commands'
export async function POST(request: Request) {
  try {
    assertSameOrigin(request)
    const key = operationKey(request)
    if (Number(request.headers.get('content-length') || 0) > 100000)
      throw new GatewayError(
        413,
        'REQUEST_TOO_LARGE',
        'The request is too large.',
      )
    const text = await request.text()
    if (Buffer.byteLength(text) > 100000)
      throw new GatewayError(
        413,
        'REQUEST_TOO_LARGE',
        'The request is too large.',
      )
    let input: unknown
    try {
      input = JSON.parse(text)
    } catch {
      throw new GatewayError(422, 'INVALID_JSON', 'Invalid request content.')
    }
    if (
      !input ||
      typeof input !== 'object' ||
      !('action' in input) ||
      typeof input.action !== 'string'
    )
      throw new GatewayError(422, 'INVALID_ACTION', 'Choose a valid action.')
    const payload = 'payload' in input ? input.payload : {}
    if (!payload || typeof payload !== 'object' || Array.isArray(payload))
      throw new GatewayError(422, 'INVALID_PAYLOAD', 'Invalid action values.')
    const data = await workspaceCommand(
      await backendFor(request),
      input.action,
      payload as Record<string, unknown>,
      key,
    )
    return Response.json({ data }, { headers: { 'Cache-Control': 'no-store' } })
  } catch (error) {
    return errorResponse(error)
  }
}
