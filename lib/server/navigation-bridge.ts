import { createHmac, randomUUID } from 'node:crypto'

type Environment = Record<string, string | undefined>

const loopback = new Set(['localhost', '127.0.0.1', '[::1]'])
const responseHeaders = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' }

function fail(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status, headers: responseHeaders })
}

export function apiBase(env: Environment): URL {
  const base = new URL(env.CAREER_KITCHEN_API_URL || 'http://127.0.0.1:8000')
  if (
    base.username || base.password || base.search || base.hash ||
    (base.protocol !== 'https:' && !(base.protocol === 'http:' && loopback.has(base.hostname)))
  ) throw new Error('Use an HTTPS API URL or a loopback development URL')
  base.pathname = base.pathname.replace(/\/$/, '') + '/'
  return base
}

export function localAuthentication(env: Environment, base: URL): boolean {
  return env.NODE_ENV === 'development' && env.ENVIRONMENT === 'development' &&
    env.AUTH_MODE === 'local' && env.ALLOW_DEV_AUTH?.toLowerCase() === 'true' &&
    loopback.has(base.hostname) && (env.DEV_JWT_SECRET?.length ?? 0) >= 32 &&
    loopback.has(new URL(env.DEV_JWT_ISSUER || 'http://127.0.0.1:8000/dev-auth').hostname)
}

function localToken(env: Environment) {
  const now = Math.floor(Date.now() / 1000)
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url')
  const claims = Buffer.from(JSON.stringify({
    sub: '8ac07b4e-e703-4a60-b0ed-35ff610b8235',
    session_id: randomUUID(),
    iss: env.DEV_JWT_ISSUER || 'http://127.0.0.1:8000/dev-auth',
    aud: env.SUPABASE_JWT_AUDIENCE || 'authenticated',
    iat: now, exp: now + 300, auth_time: now,
    email: 'website-chef-tester@fictional.example.invalid', email_verified: true,
  })).toString('base64url')
  const signature = createHmac('sha256', env.DEV_JWT_SECRET!).update(`${header}.${claims}`).digest('base64url')
  return `${header}.${claims}.${signature}`
}

function sameOrigin(request: Request) {
  const origin = request.headers.get('origin')
  // Next can normalize request.url to localhost while the browser uses 127.0.0.1.
  // Use the incoming Host authority, never a caller-selected forwarded host.
  const expected = new URL(request.url)
  const host = request.headers.get('host')
  if (host) expected.host = host
  return (!origin || origin === expected.origin) &&
    request.headers.get('sec-fetch-site') !== 'cross-site'
}

// Injectable dependencies keep authentication and proxy behavior testable without Google calls.
export function createNavigationBridge(env: Environment, fetcher: typeof fetch = fetch) {
  return {
    async GET() {
      let authentication = 'session'
      try {
        const base = apiBase(env)
        authentication = localAuthentication(env, base) ? 'local' : 'session'
        const health = await fetcher(new URL('v1/health', base), {
          cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(3000),
        })
        return Response.json({ data: {
          authentication,
          api_reachable: health.ok,
        } }, { headers: responseHeaders })
      } catch {
        return Response.json({ data: { authentication, api_reachable: false } }, {
          headers: responseHeaders,
        })
      }
    },
    async POST(request: Request) {
      if (!sameOrigin(request)) return fail(403, 'ORIGIN_FORBIDDEN', 'Use Career Chef from this website.')
      let base: URL
      let useLocal: boolean
      try {
        base = apiBase(env)
        useLocal = localAuthentication(env, base) && loopback.has(new URL(request.url).hostname)
      } catch {
        return fail(503, 'CHAT_UNAVAILABLE', 'Career Chef API connection is not configured correctly.')
      }
      const supplied = request.headers.get('authorization')
      if (supplied && (!/^Bearer [^\s]+$/.test(supplied) || supplied.length > 16400)) {
        return fail(401, 'INVALID_TOKEN', 'Enter a valid session access token.')
      }
      if (!supplied && !useLocal) return fail(401, 'UNAUTHORIZED', 'Connect a session access token to chat.')
      const key = request.headers.get('idempotency-key') || ''
      if (!/^[A-Za-z0-9_.:-]{8,128}$/.test(key)) {
        return fail(422, 'IDEMPOTENCY_KEY_REQUIRED', 'Supply an Idempotency-Key for this message.')
      }
      if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json')) {
        return fail(415, 'UNSUPPORTED_MEDIA_TYPE', 'Send the chat request as JSON.')
      }
      // Bound the decoded request before forwarding. FastAPI performs the schema validation.
      const reader = request.body?.getReader()
      if (!reader) return fail(422, 'VALIDATION_ERROR', 'A chat request body is required.')
      const parts: Uint8Array[] = []
      let length = 0
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          length += value.byteLength
          if (length > 100000) {
            await reader.cancel()
            return fail(413, 'REQUEST_TOO_LARGE', 'This conversation exceeds the request limit.')
          }
          parts.push(value)
        }
      } catch {
        return fail(400, 'INVALID_REQUEST', 'The message could not be read. Try it again.')
      }
      const body = Buffer.concat(parts)
      try { JSON.parse(body.toString('utf8')) } catch {
        return fail(422, 'VALIDATION_ERROR', 'Send a valid JSON chat request.')
      }
      try {
        const upstream = await fetcher(new URL('v1/navigation/chat', base), {
          method: 'POST', cache: 'no-store', redirect: 'error',
          headers: {
            'Content-Type': 'application/json', 'Idempotency-Key': key,
            Authorization: supplied || `Bearer ${localToken(env)}`,
          },
          body, signal: AbortSignal.timeout(40000),
        })
        const payload: unknown = await upstream.json()
        if (!upstream.ok) {
          // Never reflect provider, validation input, stack traces, or authentication details.
          const code = typeof payload === 'object' && payload && 'error' in payload &&
            typeof payload.error === 'object' && payload.error && 'code' in payload.error &&
            typeof payload.error.code === 'string' ? payload.error.code : 'CHAT_UNAVAILABLE'
          const messages: Record<string, string> = {
            CHAT_UNAVAILABLE: 'Career Chef is unavailable. Check the server Gemini key, model and quota, then retry.',
            UNAUTHORIZED: 'Connect a session access token to chat.',
            INVALID_TOKEN: 'Your session has expired or is invalid. Connect a fresh access token.',
            AUTH_UNAVAILABLE: 'The authentication service is unavailable. Try again shortly.',
            RATE_LIMITED: 'Too many messages. Wait a minute, then retry.',
            IDEMPOTENCY_CONFLICT: 'This request key was already used. Start a new message.',
            VALIDATION_ERROR: 'Check your message, Google consent and conversation length.',
            ORIGIN_FORBIDDEN: 'The API origin is not allowed. Check the server CORS configuration.',
          }
          const known = Object.hasOwn(messages, code)
          return fail(upstream.status, known ? code : 'CHAT_UNAVAILABLE',
            known ? messages[code] : 'Career Chef could not process this request. Check your session and server configuration.')
        }
        return Response.json(payload, { status: upstream.status, headers: responseHeaders })
      } catch {
        return fail(503, 'API_UNAVAILABLE', 'Career Chef could not reach the API. Start the API server, then retry.')
      }
    },
  }
}
