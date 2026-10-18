import 'server-only'
import {
  createHash,
  createHmac,
  randomUUID,
  timingSafeEqual,
} from 'node:crypto'
import { cookies } from 'next/headers'
import { createServerClient } from '@supabase/ssr'
import { GatewayError, isLoopbackHost, requestHostname } from './http-utils'

const LOCAL_COOKIE = 'ck-local-session'
const SAMPLE_COOKIE = 'ck-sample-session'
type SessionConnection = { token: string; mode: 'sample' | 'standard' }
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

export function sampleApiBase() {
  if (authMode() !== 'local')
    throw new GatewayError(
      403,
      'DEMO_DISABLED',
      'Sample demo mode is available only in local development.',
    )
  let url: URL
  let standard: URL
  try {
    url = new URL(
      process.env.CAREER_KITCHEN_SAMPLE_API_URL || 'http://127.0.0.1:8001',
    )
    standard = new URL(
      process.env.CAREER_KITCHEN_API_URL || 'http://127.0.0.1:8000',
    )
  } catch {
    throw new GatewayError(
      503,
      'DEMO_NOT_CONFIGURED',
      'Configure a separate local sample API.',
    )
  }
  if (
    !isLoopbackHost(url.hostname) ||
    !['http:', 'https:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== '/' ||
    (isLoopbackHost(standard.hostname) && url.port === standard.port)
  )
    throw new GatewayError(
      503,
      'DEMO_NOT_CONFIGURED',
      'The sample API must use a separate loopback port.',
    )
  return url.origin
}

export function sampleDemoAvailable(request: Request) {
  if (
    authMode(requestHostname(request)) !== 'local' ||
    !isLoopbackHost(new URL(request.url).hostname)
  )
    return false
  try {
    sampleApiBase()
    return true
  } catch {
    return false
  }
}

function sampleSignature(content: string) {
  return createHmac('sha256', process.env.DEV_JWT_SECRET!)
    .update(`career-kitchen/sample-session/v1:${content}`)
    .digest('base64url')
}

export async function sampleSession(
  request: Request,
): Promise<SessionConnection | null> {
  const value = (await cookies()).get(SAMPLE_COOKIE)?.value
  if (!value) return null
  if (!sampleDemoAvailable(request))
    throw new GatewayError(
      403,
      'DEMO_DISABLED',
      'Sample demo mode is available only in local development.',
    )
  const [content, signature, extra] = value.split('.')
  const expected = sampleSignature(content || '')
  if (
    !content ||
    !signature ||
    extra ||
    !/^[A-Za-z0-9_-]{43}$/.test(signature) ||
    !timingSafeEqual(Buffer.from(signature), Buffer.from(expected))
  )
    throw new GatewayError(
      401,
      'INVALID_DEMO_SESSION',
      'Enter demo mode again to refresh your session.',
    )
  try {
    const payload = JSON.parse(
      Buffer.from(content, 'base64url').toString('utf8'),
    )
    if (
      payload.mode !== 'sample' ||
      payload.base !== sampleApiBase() ||
      typeof payload.token !== 'string' ||
      !payload.token ||
      !Number.isInteger(payload.expires) ||
      payload.expires <= Math.floor(Date.now() / 1000)
    )
      throw new Error('Invalid sample session')
    return { token: payload.token, mode: 'sample' }
  } catch {
    throw new GatewayError(
      401,
      'INVALID_DEMO_SESSION',
      'Enter demo mode again to refresh your session.',
    )
  }
}

export async function currentSessionMode(request: Request) {
  return (await sampleSession(request))
    ? ('sample' as const)
    : authMode(requestHostname(request))
}

export async function hasSampleSession() {
  return Boolean((await cookies()).get(SAMPLE_COOKIE)?.value)
}

export async function sessionConnection(
  request: Request,
): Promise<SessionConnection> {
  const sample = await sampleSession(request)
  if (sample) return sample
  return { token: await standardAccessToken(request), mode: 'standard' }
}

function sessionFailure(
  error: { status?: number } | null,
  message: string,
): GatewayError {
  if (error && ![400, 401, 403].includes(error.status || 0))
    return new GatewayError(
      503,
      'AUTH_UNAVAILABLE',
      'Sign-in is temporarily unavailable. Please try again shortly.',
    )
  return new GatewayError(401, 'UNAUTHORIZED', message)
}

function accessTokenAlgorithm(token: string): string | undefined {
  try {
    const header = JSON.parse(
      Buffer.from(token.split('.')[0], 'base64url').toString('utf8'),
    )
    return typeof header?.alg === 'string' ? header.alg : undefined
  } catch {
    return undefined
  }
}

export async function accessToken(request: Request) {
  return (await sessionConnection(request)).token
}

async function standardAccessToken(request: Request) {
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
    throw sessionFailure(
      verified.error,
      'Your session expired. Please sign in again.',
    )
  const {
    data: { session },
    error,
  } = await supabase.auth.getSession()
  if (error || !session)
    throw sessionFailure(error, 'Sign in to your workspace.')
  if (accessTokenAlgorithm(session.access_token) === 'HS256') {
    // Supabase still accepts unexpired legacy tokens after an asymmetric key
    // rotation. Request one freshly signed token rather than weakening the API's
    // ES256/RS256 policy. This header only triggers refresh; it grants no access.
    const refreshed = await supabase.auth.refreshSession()
    if (refreshed.error || !refreshed.data.session)
      throw sessionFailure(
        refreshed.error,
        'Your session expired. Please sign in again.',
      )
    const token = refreshed.data.session.access_token
    const checked = await supabase.auth.getUser(token)
    if (checked.error || !checked.data.user)
      throw sessionFailure(
        checked.error,
        'Your session expired. Please sign in again.',
      )
    if (checked.data.user.id !== verified.data.user.id)
      throw new GatewayError(
        401,
        'UNAUTHORIZED',
        'Your session changed. Please sign in again.',
      )
    if (!['ES256', 'RS256'].includes(accessTokenAlgorithm(token) || ''))
      throw new GatewayError(
        503,
        'AUTH_SIGNING_NOT_READY',
        'Sign-in is being updated. Please try again shortly.',
      )
    return token
  }
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
  return localToken(
    fictionalIdentity(account),
    `${account}@fictional.example.invalid`,
  )
}

export function sampleIdentity(account: string) {
  if (account !== 'employer' && !/^candidate-\d{6}$/.test(account))
    throw new GatewayError(
      422,
      'INVALID_FIXTURE',
      'Choose a sample candidate or employer account.',
    )
  if (
    account !== 'employer' &&
    (Number(account.slice(10)) < 1 || Number(account.slice(10)) > 100000)
  )
    throw new GatewayError(
      422,
      'INVALID_FIXTURE',
      'Choose an imported sample candidate account.',
    )
  const label =
    account === 'employer'
      ? account
      : account.replace('candidate-', 'candidate-user-')
  const namespace = Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex')
  const bytes = createHash('sha1')
    .update(namespace)
    .update(`https://career-kitchen.example.invalid/samples/v1/${label}`)
    .digest()
    .subarray(0, 16)
  bytes[6] = (bytes[6] & 15) | 80
  bytes[8] = (bytes[8] & 63) | 128
  const hex = bytes.toString('hex')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function sampleToken(account: string) {
  return localToken(
    sampleIdentity(account),
    `${account}@samples.example.invalid`,
  )
}

function localToken(subject: string, email: string) {
  const now = Math.floor(Date.now() / 1000)
  const payload = {
    sub: subject,
    session_id: randomUUID(),
    iss: process.env.DEV_JWT_ISSUER || 'http://127.0.0.1:8000/dev-auth',
    aud: process.env.SUPABASE_JWT_AUDIENCE || 'authenticated',
    iat: now,
    exp: now + 1800,
    auth_time: now,
    email,
    email_verified: true,
  }
  const content = [{ alg: 'HS256', typ: 'JWT' }, payload]
    .map((x) => Buffer.from(JSON.stringify(x)).toString('base64url'))
    .join('.')
  return `${content}.${createHmac('sha256', process.env.DEV_JWT_SECRET!).update(content).digest('base64url')}`
}

export async function setFictionalSession(token: string) {
  const store = await cookies()
  store.delete(SAMPLE_COOKIE)
  store.set(LOCAL_COOKIE, token, {
    httpOnly: true,
    sameSite: 'strict',
    secure: false,
    path: '/',
    maxAge: 1800,
  })
}
export async function clearFictionalSession() {
  const store = await cookies()
  store.delete(LOCAL_COOKIE)
  store.delete(SAMPLE_COOKIE)
}

export async function setSampleSession(token: string) {
  const content = Buffer.from(
    JSON.stringify({
      mode: 'sample',
      base: sampleApiBase(),
      token,
      expires: Math.floor(Date.now() / 1000) + 1800,
    }),
  ).toString('base64url')
  const store = await cookies()
  store.delete(LOCAL_COOKIE)
  store.set(SAMPLE_COOKIE, `${content}.${sampleSignature(content)}`, {
    httpOnly: true,
    sameSite: 'strict',
    secure: false,
    path: '/',
    maxAge: 1800,
  })
}
