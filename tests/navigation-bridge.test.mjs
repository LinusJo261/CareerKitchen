import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

// Exercise the real transport without importing Next's request-scoped cookies.
const url = new URL('../lib/server/navigation-bridge.ts', import.meta.url)
const source = ts.transpileModule(readFileSync(url, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const module = { exports: {} }
new Function('require', 'module', 'exports', source)(createRequire(url), module, module.exports)
const { createNavigationBridge } = module.exports

const env = { NODE_ENV: 'production', CAREER_KITCHEN_API_URL: 'https://api.example.test' }
const origin = 'https://career.example.test'
const body = JSON.stringify({ message: 'Where are my opportunities?', consent_to_gemini: true, history: [] })
function request(method = 'POST', headers = {}) {
  return new Request(`${origin}/api/navigation/chat`, {
    method,
    headers: {
      Origin: origin,
      'Content-Type': 'application/json',
      'Idempotency-Key': 'question-12345678',
      Cookie: 'workspace=fixture-only',
      ...headers,
    },
    ...(method === 'POST' ? { body } : {}),
  })
}
function authError(status, code) {
  return Object.assign(new Error('private-authentication-diagnostic'), { status, code })
}
const unavailable = () => assert.fail('must not contact upstream')

test('connection health reports a verified cookie session without exposing its token', async () => {
  const bridge = createNavigationBridge(env, async (url, options) => {
    assert.equal(String(url), 'https://api.example.test/v1/health')
    assert.equal(options.headers, undefined)
    return Response.json({ status: 'ok' })
  }, async incoming => {
    assert.equal(incoming.headers.get('cookie'), 'workspace=fixture-only')
    return 'private-cookie-token'
  })
  const response = await bridge.GET(request('GET'))
  assert.equal(response.headers.get('cache-control'), 'no-store')
  assert.deepEqual(await response.json(), {
    data: { authentication: 'session', api_reachable: true, session_available: true },
  })
})

test('cookie authentication forwards the exact message and retry key only to the configured API', async () => {
  const bridge = createNavigationBridge(env, async (url, options) => {
    assert.equal(String(url), 'https://api.example.test/v1/navigation/chat')
    assert.equal(options.headers.Authorization, 'Bearer private-cookie-token')
    assert.equal(options.headers.Cookie, undefined)
    assert.equal(options.headers['Idempotency-Key'], 'question-12345678')
    assert.equal(options.body.toString(), body)
    assert.equal(options.redirect, 'error')
    assert.equal(options.cache, 'no-store')
    return Response.json({ data: { reply: 'Open Opportunities.', links: [], version: 1 } })
  }, async () => 'private-cookie-token')
  const response = await bridge.POST(request())
  assert.equal(response.status, 200)
  assert.doesNotMatch(await response.text(), /private-cookie-token/)
})

test('explicit bearer authentication takes precedence and malformed credentials never resolve cookies', async () => {
  const bridge = createNavigationBridge(env, async (_url, options) => {
    assert.equal(options.headers.Authorization, 'Bearer explicit-token')
    return Response.json({ data: {} })
  }, async () => assert.fail('explicit bearer must not read the cookie session'))
  assert.equal((await bridge.POST(request('POST', { Authorization: 'Bearer explicit-token' }))).status, 200)
  assert.equal((await bridge.POST(request('POST', { Authorization: 'Basic invalid' }))).status, 401)
})

test('foreign origins and malformed hosts are rejected before reading sessions or contacting upstream', async () => {
  const bridge = createNavigationBridge(env, unavailable, async () => assert.fail('must not read cookies'))
  for (const headers of [
    { Origin: 'https://foreign.example.test' },
    { 'Sec-Fetch-Site': 'cross-site' },
    { Host: 'career.example.test/path' },
  ]) {
    assert.equal((await bridge.POST(request('POST', headers))).status, 403)
    assert.equal((await bridge.GET(request('GET', headers))).status, 403)
  }
})

test('anonymous and unconfigured sessions fail safely while health remains useful', async () => {
  for (const [status, code, expected] of [[401, 'UNAUTHORIZED', 401], [503, 'AUTH_NOT_CONFIGURED', 503]]) {
    const resolve = async () => { throw authError(status, code) }
    const health = createNavigationBridge(env, async () => Response.json({ status: 'ok' }), resolve)
    assert.deepEqual((await (await health.GET(request('GET'))).json()).data, {
      authentication: 'session', api_reachable: true, session_available: false,
    })
    const response = await createNavigationBridge(env, unavailable, resolve).POST(request())
    assert.equal(response.status, expected)
    assert.doesNotMatch(await response.text(), /private-authentication-diagnostic/)
  }
})

test('local development prefers the workspace identity and preserves explicit local fallback', async () => {
  const local = {
    NODE_ENV: 'development', ENVIRONMENT: 'development', AUTH_MODE: 'local',
    ALLOW_DEV_AUTH: 'true', DEV_JWT_SECRET: 'fixture-only-local-secret-1234567890',
  }
  const localRequest = () => new Request('http://localhost:3000/api/navigation/chat', {
    method: 'POST', headers: {
      Origin: 'http://localhost:3000', 'Content-Type': 'application/json', 'Idempotency-Key': 'question-12345678',
    }, body,
  })
  const tokens = []
  const fetcher = async (_url, options) => {
    tokens.push(options.headers.Authorization)
    return Response.json({ data: {} })
  }
  assert.equal((await createNavigationBridge(local, fetcher, async () => 'workspace-token').POST(localRequest())).status, 200)
  assert.equal(tokens[0], 'Bearer workspace-token')
  assert.equal((await createNavigationBridge(local, fetcher, async () => {
    throw authError(401, 'UNAUTHORIZED')
  }).POST(localRequest())).status, 200)
  const claims = JSON.parse(Buffer.from(tokens[1].split('.')[1], 'base64url').toString())
  assert.equal(claims.email, 'website-chef-tester@fictional.example.invalid')
  for (const error of [authError(403, 'FORBIDDEN'), new Error('unexpected-auth-service-failure')]) {
    const response = await createNavigationBridge(local, unavailable, async () => { throw error }).POST(localRequest())
    assert.equal(response.status, 'status' in error ? 403 : 503)
  }
})

test('each concurrent request resolves its own session and invalid resolver tokens fail closed', async () => {
  const bridge = createNavigationBridge(env, async (_url, options) => Response.json({
    data: { identity: options.headers.Authorization },
  }), async incoming => incoming.headers.get('cookie').split('=')[1])
  const responses = await Promise.all(['first-user', 'second-user'].map(value =>
    bridge.POST(request('POST', { Cookie: `workspace=${value}` })),
  ))
  assert.deepEqual(await Promise.all(responses.map(response => response.json())), [
    { data: { identity: 'Bearer first-user' } }, { data: { identity: 'Bearer second-user' } },
  ])
  for (const token of ['', 'invalid token', 'x'.repeat(16400)]) {
    assert.equal((await createNavigationBridge(env, unavailable, async () => token).POST(request())).status, 401)
  }
})
