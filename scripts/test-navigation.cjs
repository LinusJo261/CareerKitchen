/* Real transport/auth regressions with injected HTTP dependencies; no paid Google calls. */
const { test } = require('node:test')
const assert = require('node:assert/strict')
const { createHmac } = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')

function loadTS(relative) {
  const filename = path.resolve(__dirname, '..', relative)
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const loaded = new Module(filename, module)
  loaded.filename = filename
  loaded.paths = module.paths
  loaded._compile(output, filename)
  return loaded.exports
}

const { apiBase, localAuthentication, createNavigationBridge } = loadTS('lib/server/navigation-bridge.ts')
const { navigationHistory, parseNavigationReply, navigationError } = loadTS('lib/navigation-chat.ts')
const { chefGuides, chefContext } = loadTS('lib/career-chef-guide.ts')
const dev = {
  NODE_ENV: 'development', ENVIRONMENT: 'development', AUTH_MODE: 'local',
  ALLOW_DEV_AUTH: 'true', DEV_JWT_SECRET: 'unit-test-only-'.repeat(4),
}
const body = JSON.stringify({ message: 'Where do I find jobs?', consent_to_gemini: true, history: [] })
function question(overrides = {}) {
  return new Request(overrides.url ?? 'http://localhost:3000/api/navigation/chat', {
    method: 'POST', headers: {
      'Content-Type': 'application/json', 'Idempotency-Key': 'test-request-001',
      Origin: 'http://localhost:3000', ...overrides.headers,
    }, body: overrides.body ?? body,
  })
}
function connection(headers = {}, url = 'http://localhost:3000/api/navigation/chat') {
  return new Request(url, { headers })
}

test('only HTTPS or loopback API URLs accept session credentials', () => {
  for (const url of ['http://api.example.com', 'https://user:pass@example.com', 'https://example.com?key=x', 'https://example.com#token']) {
    assert.throws(() => apiBase({ CAREER_KITCHEN_API_URL: url }))
  }
  assert.equal(apiBase({}).href, 'http://127.0.0.1:8000/')
  assert.equal(apiBase({ CAREER_KITCHEN_API_URL: 'https://api.example.com/prefix' }).pathname, '/prefix/')
})

test('fictional local identity is disabled outside explicit local development', () => {
  const base = apiBase(dev)
  assert.equal(localAuthentication(dev, base), true)
  for (const override of [
    { NODE_ENV: 'production' }, { ENVIRONMENT: 'production' }, { AUTH_MODE: 'supabase' },
    { ALLOW_DEV_AUTH: 'false' }, { DEV_JWT_SECRET: '' }, { DEV_JWT_ISSUER: 'https://identity.example.com' },
  ]) assert.equal(localAuthentication({ ...dev, ...override }, base), false)
  assert.equal(localAuthentication(dev, new URL('https://api.example.com')), false)
})

test('production requires a real bearer session before contacting the API', async () => {
  const bridge = createNavigationBridge({ ...dev, NODE_ENV: 'production' }, () => assert.fail('must not call upstream'))
  const response = await bridge.POST(question())
  assert.equal(response.status, 401)
  assert.equal((await response.json()).error.code, 'UNAUTHORIZED')
})

test('cross-origin requests are rejected before authentication or forwarding', async () => {
  const bridge = createNavigationBridge(dev, () => assert.fail('must not call upstream'))
  assert.equal((await bridge.POST(question({ headers: { Origin: 'https://elsewhere.example' } }))).status, 403)
  assert.equal((await bridge.POST(question({ headers: { 'Sec-Fetch-Site': 'cross-site' } }))).status, 403)
})

test('Next normalized localhost URL still accepts the browser Host origin', async () => {
  const bridge = createNavigationBridge(dev, async () => Response.json({ data: {} }))
  const response = await bridge.POST(question({ headers: {
    Host: '127.0.0.1:3000', Origin: 'http://127.0.0.1:3000',
  } }))
  assert.equal(response.status, 200)
  assert.equal((await bridge.POST(question({ headers: {
    Host: '127.0.0.1:3000', Origin: 'https://elsewhere.example',
    'X-Forwarded-Host': 'elsewhere.example',
  } }))).status, 403)
  // Host without a port represents the default HTTP port, not Next's port.
  assert.equal((await bridge.POST(question({ headers: {
    Host: 'localhost', Origin: 'http://localhost',
  } }))).status, 200)
})

test('Next normalized LAN and hosted authorities cannot obtain local development identity', async () => {
  const bridge = createNavigationBridge(dev, () => assert.fail('must not call upstream'))
  for (const host of ['192.168.1.23:3000', 'career.example.com:3000']) {
    const response = await bridge.POST(question({ headers: { Host: host, Origin: `http://${host}` } }))
    assert.equal(response.status, 401)
    assert.equal((await response.json()).error.code, 'UNAUTHORIZED')
  }
  // A forwarded host never opts a remote authority into development auth.
  const response = await bridge.POST(question({ headers: {
    Host: '192.168.1.23:3000', Origin: 'http://192.168.1.23:3000', 'X-Forwarded-Host': 'localhost:3000',
  } }))
  assert.equal(response.status, 401)
  assert.equal((await bridge.POST(question({
    url: 'http://career.example.com:3000/api/navigation/chat',
    headers: { Host: 'localhost:3000' },
  }))).status, 401)
})

test('connection health reports local authentication only for loopback website authorities', async () => {
  const bridge = createNavigationBridge(dev, async () => Response.json({ status: 'ok' }))
  for (const host of ['localhost:3000', '127.0.0.1:3000', '[::1]:3000']) {
    const response = await bridge.GET(connection({ Host: host }))
    assert.deepEqual((await response.json()).data, { authentication: 'local', api_reachable: true })
    assert.equal(response.headers.get('cache-control'), 'no-store')
  }
  for (const host of ['192.168.1.23:3000', 'career.example.com:3000']) {
    const response = await bridge.GET(connection({ Host: host, 'X-Forwarded-Host': 'localhost:3000' }))
    assert.deepEqual((await response.json()).data, { authentication: 'session', api_reachable: true })
  }
  const production = createNavigationBridge({ ...dev, NODE_ENV: 'production' }, async () => Response.json({}))
  assert.equal((await (await production.GET(connection())).json()).data.authentication, 'session')
})

test('malformed Host authorities fail closed before authentication or forwarding', async () => {
  const bridge = createNavigationBridge(dev, () => assert.fail('must not call upstream'))
  for (const host of ['localhost:3000/path', 'localhost:3000?x=1', 'elsewhere@localhost:3000', 'localhost:99999']) {
    assert.equal((await bridge.POST(question({ headers: { Host: host } }))).status, 403)
  }
})

test('local API gets signed role-free identity and exact retry body/key', async () => {
  const received = []
  const bridge = createNavigationBridge(dev, async (url, init) => {
    received.push({ url: String(url), init })
    return Response.json({ data: { reply: 'Open Opportunities.', links: [{ label: 'Opportunities', path: '/candidate/opportunities' }], version: 1 } })
  })
  for (let i = 0; i < 2; i++) assert.equal((await bridge.POST(question())).status, 200)
  for (const { url, init } of received) {
    assert.equal(url, 'http://127.0.0.1:8000/v1/navigation/chat')
    assert.equal(init.body.toString(), body)
    assert.equal(init.headers['Idempotency-Key'], 'test-request-001')
    const [header, claims, signature] = init.headers.Authorization.slice(7).split('.')
    assert.equal(signature, createHmac('sha256', dev.DEV_JWT_SECRET).update(`${header}.${claims}`).digest('base64url'))
    const identity = JSON.parse(Buffer.from(claims, 'base64url').toString())
    assert.equal(identity.email, 'website-chef-tester@fictional.example.invalid')
    assert.equal(identity.exp - identity.iat, 300)
    assert.equal(identity.aud, 'authenticated')
    assert.equal(identity.role, undefined)
    assert.equal(identity.platform_roles, undefined)
  }
})

test('session token passes only to configured API with redirects disabled', async () => {
  let called = false
  const bridge = createNavigationBridge({ CAREER_KITCHEN_API_URL: 'https://api.example.com' }, async (url, init) => {
    called = true
    assert.equal(String(url), 'https://api.example.com/v1/navigation/chat')
    assert.equal(init.headers.Authorization, 'Bearer session-test-value')
    assert.equal(init.redirect, 'error')
    assert.equal(init.cache, 'no-store')
    return Response.json({ data: {} })
  })
  await bridge.POST(question({ headers: { Authorization: 'Bearer session-test-value' } }))
  assert.equal(called, true)
})

test('malformed, oversized and missing-key requests never contact upstream', async () => {
  const bridge = createNavigationBridge(dev, () => assert.fail('must not call upstream'))
  assert.equal((await bridge.POST(question({ body: '{' }))).status, 422)
  assert.equal((await bridge.POST(question({ body: 'x'.repeat(100001) }))).status, 413)
  assert.equal((await bridge.POST(question({ headers: { 'Idempotency-Key': 'short' } }))).status, 422)
  assert.equal((await bridge.POST(question({ headers: { 'Content-Type': 'text/plain' } }))).status, 415)
  assert.equal((await bridge.POST(question({ headers: { Authorization: 'Basic invalid' } }))).status, 401)
})

test('upstream diagnostics and invalid validation inputs never reach the browser', async () => {
  const bridge = createNavigationBridge(dev, async () => Response.json({ error: {
    code: 'CHAT_UNAVAILABLE', message: 'private-provider-debug-value', input: 'private-question',
  } }, { status: 503 }))
  const response = await bridge.POST(question())
  const result = await response.text()
  assert.equal(response.status, 503)
  assert.equal(response.headers.get('cache-control'), 'no-store')
  assert.ok(!result.includes('private-'))
  const offline = createNavigationBridge(dev, async () => { throw new Error('private-network-error') })
  assert.equal((await offline.POST(question())).status, 503)
  assert.deepEqual((await (await offline.GET(connection())).json()).data, { authentication: 'local', api_reachable: false })
})

test('upstream failures give useful user guidance without server setup instructions', async () => {
  for (const code of ['CHAT_UNAVAILABLE', 'ORIGIN_FORBIDDEN', 'UNEXPECTED_PROVIDER_FAILURE']) {
    const bridge = createNavigationBridge(dev, async () => Response.json({ error: {
      code, message: 'private-provider-debug-value',
    } }, { status: 503 }))
    const response = await bridge.POST(question())
    const result = await response.json()
    assert.equal(response.status, 503)
    assert.match(result.error.message, /Career Chef/)
    assert.doesNotMatch(result.error.message, /Gemini key|CORS|server configuration|private-provider/)
  }
  assert.doesNotMatch(navigationError(null, 503), /Gemini key|server-side|configuration/)
})

test('a reachable API with no chat endpoint gives a safe availability error', async () => {
  for (const status of [404, 405]) {
    for (const json of [true, false]) {
      const bridge = createNavigationBridge(dev, async url => {
        if (new URL(url).pathname === '/v1/health') return Response.json({ status: 'ok' })
        return json
          ? Response.json({ detail: 'private-upstream-route-detail' }, { status })
          : new Response('<html>private-upstream-route-detail</html>', { status })
      })
      assert.deepEqual((await (await bridge.GET(connection())).json()).data, {
        authentication: 'local', api_reachable: true,
      })
      const response = await bridge.POST(question())
      assert.equal(response.status, 503)
      assert.deepEqual((await response.json()).error, {
        code: 'CHAT_UNAVAILABLE',
        message: 'AI chat is not available on the connected service. Quick guides are still available.',
      })
      assert.equal(response.headers.get('cache-control'), 'no-store')
    }
  }
})

test('UI sends only the newest whole conversation pairs within API budgets', () => {
  const turns = Array.from({ length: 8 }, (_, index) => [
    { role: 'user', content: `Question ${index}` }, { role: 'assistant', content: `Answer ${index}` },
  ]).flat()
  const history = navigationHistory(turns, 'Next question')
  assert.equal(history.length, 10)
  assert.equal(history[0].content, 'Question 3')
  const large = [
    { role: 'user', content: 'u'.repeat(2000) }, { role: 'assistant', content: 'a'.repeat(4000) },
    { role: 'user', content: '😀'.repeat(2000) }, { role: 'assistant', content: 'a'.repeat(4000) },
  ]
  assert.equal(navigationHistory(large, 'Next').length, 2)
  assert.deepEqual(navigationHistory([{ role: 'assistant', content: 'unfinished' }], 'Next'), [])
})

test('UI rejects external or unknown links and invalid provider replies', () => {
  const valid = { data: { reply: 'Open your profile.', links: [{ label: 'Profile', path: '/candidate/profile' }], version: 1 } }
  assert.equal(parseNavigationReply(valid).reply, 'Open your profile.')
  for (const destination of ['https://external.example', '//external.example', '/candidate/not-a-page', 'javascript:alert(1)']) {
    assert.equal(parseNavigationReply({ data: { ...valid.data, links: [{ label: 'Page', path: destination }] } }), null)
  }
  assert.equal(parseNavigationReply({ data: { ...valid.data, reply: 'x'.repeat(4001) } }), null)
  assert.equal(parseNavigationReply({ data: { ...valid.data, version: 2 } }), null)
})

test('UI accepts the full Unicode reply budget and rejects malformed chat envelopes', () => {
  const valid = { data: { reply: '😀'.repeat(4000), links: [], version: 1 } }
  assert.equal(Array.from(parseNavigationReply(valid).reply).length, 4000)
  for (const invalid of [
    null, {}, { data: null }, { data: [] },
    { data: { ...valid.data, reply: '   ' } },
    { data: { ...valid.data, reply: '😀'.repeat(4001) } },
    { data: { ...valid.data, links: [{ label: ' ', path: '/get-started' }] } },
    { data: { ...valid.data, links: [{ label: 'x'.repeat(201), path: '/get-started' }] } },
    { data: { ...valid.data, links: Array(4).fill({ label: 'Start', path: '/get-started' }) } },
  ]) assert.equal(parseNavigationReply(invalid), null)
})

test('curated onboarding guides link only to existing local website pages', () => {
  for (const guide of chefGuides) {
    for (const step of guide.steps) {
      if (!step.path) continue
      const destination = new URL(step.path, 'https://career.example.invalid')
      assert.equal(destination.origin, 'https://career.example.invalid')
      assert.match(destination.pathname, /^(?:\/get-started|\/(?:candidate|employer|onboarding)\/[a-z-]+)$/)
      if (destination.search) assert.equal(destination.search, '?role=candidate')
      assert.equal(typeof step.label, 'string')
      const page = path.resolve(__dirname, '..', 'app', destination.pathname.slice(1), 'page.tsx')
      assert.ok(fs.existsSync(page), `Missing guide page: ${step.path}`)
    }
  }
})

test('contextual guide suggestions use public route families without claiming account state', () => {
  assert.equal(chefContext('/onboarding/candidate').guide, 'candidate')
  assert.equal(chefContext('/onboarding/candidate/preferences').guide, 'candidate')
  assert.equal(chefContext('/employer/vacancies').guide, 'employer')
  assert.equal(chefContext('/candidate/profile').guide, 'candidate')
  assert.deepEqual(chefContext('/candidate/profile'), chefContext('/candidate/privacy'))
  assert.deepEqual(chefContext('/employer/team'), chefContext('/employer/vacancies'))
  for (const pathname of [
    '/', '/get-started', '/career-chef', '/sign-in', '/candidate-not-a-route',
    '/employers', '/onboarding', '/onboarding/employer', '/onboarding/candidate-archive',
  ]) {
    assert.equal(chefContext(pathname).guide, null)
  }
})
