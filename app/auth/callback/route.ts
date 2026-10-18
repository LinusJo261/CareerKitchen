import { supabaseServer } from '@/lib/server/session'
export async function GET(request: Request) {
  const url = new URL(request.url),
    code = url.searchParams.get('code')
  if (code) {
    const result = await (
      await supabaseServer()
    ).auth.exchangeCodeForSession(code)
    if (!result.error) return Response.redirect(new URL('/candidate', url))
  }
  return Response.redirect(new URL('/sign-in?confirmation=failed', url))
}
