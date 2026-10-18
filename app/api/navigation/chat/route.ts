import { createNavigationBridge } from '@/lib/server/navigation-bridge'

export const runtime = 'nodejs'

export async function GET() {
  return createNavigationBridge(process.env).GET()
}

export async function POST(request: Request) {
  return createNavigationBridge(process.env).POST(request)
}
