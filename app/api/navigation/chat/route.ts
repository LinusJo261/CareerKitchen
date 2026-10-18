import { createNavigationBridge } from '@/lib/server/navigation-bridge'
import { accessToken, sampleApiBase, sampleSession } from '@/lib/server/session'
import { errorResponse } from '@/lib/server/http-utils'

export const runtime = 'nodejs'

export async function GET(request: Request) {
  return route(request, 'GET')
}

export async function POST(request: Request) {
  return route(request, 'POST')
}

async function route(request: Request, method: 'GET' | 'POST') {
  try {
    const sample = await sampleSession(request)
    if (!sample)
      return createNavigationBridge(process.env, fetch, accessToken)[method](
        request,
      )
    // The selected workspace determines both destination and credentials. A
    // browser-supplied bearer token must not cross the sample market boundary.
    const headers = new Headers(request.headers)
    headers.delete('authorization')
    const isolated = new Request(request, { headers })
    return createNavigationBridge(
      {
        ...process.env,
        CAREER_KITCHEN_API_URL: sampleApiBase(),
        AUTH_MODE: 'sample',
      },
      fetch,
      async () => sample.token,
    )[method](isolated)
  } catch (error) {
    return errorResponse(error)
  }
}
