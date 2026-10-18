import { randomUUID } from 'node:crypto'
import {
  assertSameOrigin,
  errorResponse,
  requestHostname,
  GatewayError,
} from '@/lib/server/http-utils'
import {
  authMode,
  clearFictionalSession,
  hasSampleSession,
  supabaseServer,
} from '@/lib/server/session'
import { backendFor } from '@/lib/server/backend'
export async function POST(request: Request) {
  try {
    assertSameOrigin(request)
    const sample = await hasSampleSession()
    try {
      const backend = await backendFor(request)
      await backend.request('/v1/sessions/logout', {
        method: 'POST',
        key: request.headers.get('idempotency-key') || randomUUID(),
      })
    } catch (error) {
      // Expired, revoked and inactive sessions still need their cookies cleared.
      if (
        !(error instanceof GatewayError) ||
        (!sample && ![401, 403].includes(error.status))
      )
        throw error
    }
    if (!sample && authMode(requestHostname(request)) === 'supabase') {
      const result = await (await supabaseServer()).auth.signOut()
      if (result.error)
        throw new GatewayError(
          503,
          'SIGN_OUT_INCOMPLETE',
          'Provider sign-out could not be confirmed. Please try again.',
        )
    }
    await clearFictionalSession()
    return Response.json(
      { status: 'SIGNED_OUT' },
      { headers: { 'Cache-Control': 'no-store' } },
    )
  } catch (error) {
    return errorResponse(error)
  }
}
