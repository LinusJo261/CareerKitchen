import 'server-only'
import { createHash, createHmac, randomUUID } from 'node:crypto'
import { cookies } from 'next/headers'
import { createServerClient } from '@supabase/ssr'
import { GatewayError, isLoopbackHost, requestHostname } from './http-utils'

const LOCAL_COOKIE = 'ck-local-session'
export function authMode(
  hostname?: string,
): 'local' | 'supabase' | 'unconfigured' {
  const local =
    process.env.NODE_ENV !== 'production' &&
    process.env.FRONTEND_LOCAL_DEMO === 'true' &&
    process.env.AUTH_MODE === 'local' &&
    process.env.ALLOW_DEV_AUTH === 'true' &&
    Boolean(
      process.env.DEV_JWT_SECRET && process.env.DEV_JWT_SECRET.length >= 32,
    )
  if (local && (!hostname || isLoopbackHost(hostname))) return 'local'
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL
  const key =
    process.env.SUPABASE_PUBLISHABLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
  if (
    url?.startsWith('https://') &&
    !url.includes('YOUR_PROJECT') &&
    key &&
    !key.startsWith('REPLACE_')
  )
    return 'supabase'
  return 'unconfigured'
}

export async function supabaseServer() {
  const store = await cookies()
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL!
  const key =
    process.env.SUPABASE_PUBLISHABLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!
  return createServerClient(url, key, {
    cookieOptions: {
      httpOnly: true,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
    },
    cookies: {
      getAll: () => store.getAll(),
      setAll: (values) => {
        for (const { name, value, options } of values)
          store.set(name, value, options)
      },
    },
  })
}

export async function accessToken(request: Request) {
  const mode = authMode(requestHostname(request))
  if (mode === 'local') {
    const token = (await cookies()).get(LOCAL_COOKIE)?.value
    if (!token)
      throw new GatewayError(401, 'UNAUTHORIZED', 'Sign in to your workspace.')
    return token
  }
  if (mode !== 'supabase')
    throw new GatewayError(
      503,
      'AUTH_NOT_CONFIGURED',
      'Sign-in is not configured. Set the Supabase connection or enable local fictional fixtures.',
    )
  const supabase = await supabaseServer()
  const verified = await supabase.auth.getUser()
  if (verified.error || !verified.data.user)
    throw new GatewayError(
      401,
      'UNAUTHORIZED',
      'Your session expired. Please sign in again.',
    )
  const {
    data: { session },
    error,
  } = await supabase.auth.getSession()
  if (error || !session)
    throw new GatewayError(401, 'UNAUTHORIZED', 'Sign in to your workspace.')
  return session.access_token
}

export function fictionalIdentity(account: string) {
  // Same UUIDv5 namespace/name as scripts.seed_demo.identity; no privileged fixtures.
  const namespace = Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex')
  const bytes = createHash('sha1')
    .update(namespace)
    .update(`https://career-kitchen.example.invalid/fictional/${account}`)
    .digest()
    .subarray(0, 16)
  bytes[6] = (bytes[6] & 15) | 80
  bytes[8] = (bytes[8] & 63) | 128
  const hex = bytes.toString('hex')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function fictionalToken(account: string) {
  if (!/^(employer|candidate-(?:0[1-9]|[12][0-9]|30))$/.test(account))
    throw new GatewayError(
      422,
      'INVALID_FIXTURE',
      'Choose a fictional candidate or employer account.',
    )
  const now = Math.floor(Date.now() / 1000)
  const payload = {
    sub: fictionalIdentity(account),
    session_id: randomUUID(),
    iss: process.env.DEV_JWT_ISSUER || 'http://127.0.0.1:8000/dev-auth',
    aud: process.env.SUPABASE_JWT_AUDIENCE || 'authenticated',
    iat: now,
    exp: now + 1800,
    auth_time: now,
    email: `${account}@fictional.example.invalid`,
    email_verified: true,
  }
  const content = [{ alg: 'HS256', typ: 'JWT' }, payload]
    .map((x) => Buffer.from(JSON.stringify(x)).toString('base64url'))
    .join('.')
  return `${content}.${createHmac('sha256', process.env.DEV_JWT_SECRET!).update(content).digest('base64url')}`
}

export async function setFictionalSession(token: string) {
  ;(await cookies()).set(LOCAL_COOKIE, token, {
    httpOnly: true,
    sameSite: 'strict',
    secure: false,
    path: '/',
    maxAge: 1800,
  })
}
export async function clearFictionalSession() {
  ;(await cookies()).delete(LOCAL_COOKIE)
}
