import { backendFor } from '@/lib/server/backend'
import { currentSessionMode } from '@/lib/server/session'
import { errorResponse } from '@/lib/server/http-utils'
import { workspaceState } from '@/lib/server/workspace-state'
export async function GET(request: Request) {
  try {
    const url = new URL(request.url),
      role =
        url.searchParams.get('role') === 'employer' ? 'employer' : 'candidate'
    const state = await workspaceState(
      await backendFor(request),
      role,
      await currentSessionMode(request),
    )
    return Response.json(state, { headers: { 'Cache-Control': 'no-store' } })
  } catch (error) {
    return errorResponse(error)
  }
}
