import { createNavigationBridge } from '@/lib/server/navigation-bridge'
import { accessToken } from '@/lib/server/session'

export const runtime = 'nodejs'

export async function GET(request: Request) {
  return createNavigationBridge(process.env, fetch, accessToken).GET(request)
}

export async function POST(request: Request) {
  return createNavigationBridge(process.env, fetch, accessToken).POST(request)
}
