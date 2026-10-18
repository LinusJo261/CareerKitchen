// Run with: node --conditions=react-server --test tests/frontend-gateway.test.mjs
// Transpile the actual TypeScript modules in memory, retaining server-only's guard.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import ts from 'typescript'

const modules = new Map()
function loadTypeScript(url) {
  const filename = fileURLToPath(url)
  if (modules.has(filename)) return modules.get(filename).exports
  const module = { exports: {} }
  modules.set(filename, module)
  const source = ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: filename,
  }).outputText
  const require = createRequire(url)
  const resolve = (name) =>
    name.startsWith('.')
      ? loadTypeScript(new URL(`${name}.ts`, url))
      : require(name)
  new Function(
    'exports',
    'require',
    'module',
    '__filename',
    '__dirname',
    source,
  )(module.exports, resolve, module, filename, dirname(filename))
  return module.exports
}

const {
  GatewayError,
  assertSameOrigin,
  isLoopbackHost,
  apiBase,
  errorResponse,
  operationKey,
} = loadTypeScript(new URL('../lib/server/http-utils.ts', import.meta.url))
const { workspaceCommand } = loadTypeScript(
  new URL('../lib/server/workspace-commands.ts', import.meta.url),
)
const { currentClaim, currentTerms, currentDisclosure } = loadTypeScript(
  new URL('../lib/server/consent-view.ts', import.meta.url),
)
const { authMode, fictionalToken } = loadTypeScript(
  new URL('../lib/server/session.ts', import.meta.url),
)
const ORIGIN = 'https://career.example'
const ID = '12345678-1234-4234-8234-123456789abc'
const OTHER_ID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
const THIRD_ID = '11111111-2222-4333-8444-555555555555'
const KEY = 'operation-12345678'

test('fictional sign-in is opt-in, loopback-only and disabled in production', () => {
  const values = {
    NODE_ENV: 'development',
    FRONTEND_LOCAL_DEMO: 'true',
    AUTH_MODE: 'local',
    ALLOW_DEV_AUTH: 'true',
    DEV_JWT_SECRET: 'fictional-test-signing-key-at-least-32-characters',
    SUPABASE_URL: '',
    SUPABASE_PUBLISHABLE_KEY: '',
    NEXT_PUBLIC_SUPABASE_URL: '',
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: '',
  }
  const previous = Object.fromEntries(
    Object.keys(values).map((key) => [key, process.env[key]]),
  )
  try {
    Object.assign(process.env, values)
    assert.equal(authMode('localhost'), 'local')
    assert.equal(authMode('127.0.0.1'), 'local')
    assert.equal(authMode('remote.example'), 'unconfigured')
    process.env.FRONTEND_LOCAL_DEMO = 'false'
    assert.equal(authMode('localhost'), 'unconfigured')
    process.env.FRONTEND_LOCAL_DEMO = 'true'
    process.env.NODE_ENV = 'production'
    assert.equal(authMode('localhost'), 'unconfigured')
    for (const account of [
      'operations',
      'verifier',
      'candidate-31',
      'arbitrary-user',
    ])
      assert.throws(
        () => fictionalToken(account),
        (error) =>
          error instanceof GatewayError &&
          error.code === 'INVALID_FIXTURE' &&
          error.status === 422,
      )
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }
})

test('consent display stops sharing when role terms or verified evidence expire', () => {
  const now = Date.parse('2026-10-17T12:00:00Z')
  const future = '2026-10-18T12:00:00Z'
  const past = '2026-10-16T12:00:00Z'
  const vacancy = {
    id: ID,
    org_id: OTHER_ID,
    version: 3,
    terms_hash: 'current',
    state: 'ACTIVE',
  }
  const claim = {
    id: THIRD_ID,
    status: 'VERIFIED',
    verified_at: past,
    expires_at: future,
    has_document: false,
  }
  const grant = {
    claim_id: THIRD_ID,
    vacancy_id: ID,
    org_id: OTHER_ID,
    role_version: 3,
    expires_at: future,
    revoked_at: null,
    kind: 'DISCLOSE_SUMMARY',
  }
  const terms = {
    vacancy_id: ID,
    role_version: 3,
    terms_hash: 'current',
    expires_at: future,
    revoked_at: null,
  }
  assert.equal(currentClaim(claim, now), true)
  assert.equal(currentDisclosure(grant, vacancy, claim, now), true)
  assert.equal(currentTerms(terms, vacancy, now), true)
  assert.equal(currentTerms(terms, { ...vacancy, version: 4 }, now), false)
  assert.equal(
    currentTerms({ ...terms, terms_hash: 'old' }, vacancy, now),
    false,
  )
  assert.equal(
    currentTerms({ ...terms, revoked_at: past }, vacancy, now),
    false,
  )
  assert.equal(
    currentDisclosure(grant, vacancy, { ...claim, expires_at: past }, now),
    false,
  )
  assert.equal(
    currentDisclosure(grant, vacancy, { ...claim, status: 'REVOKED' }, now),
    false,
  )
  assert.equal(
    currentDisclosure({ ...grant, org_id: THIRD_ID }, vacancy, claim, now),
    false,
  )
  assert.equal(
    currentDisclosure(
      { ...grant, kind: 'DISCLOSE_DOCUMENT' },
      vacancy,
      claim,
      now,
    ),
    false,
  )
  assert.equal(
    currentDisclosure(grant, { ...vacancy, state: 'CLOSED' }, claim, now),
    false,
  )
})
const request = (headers = {}) =>
  new Request(`${ORIGIN}/api/workspace/commands`, { method: 'POST', headers })
const errorCode = (code, status) => (error) =>
  error instanceof GatewayError &&
  error.code === code &&
  (status === undefined || error.status === status)
function mockBackend(reads = {}) {
  const calls = []
  const readCalls = []
  return {
    calls,
    readCalls,
    async request(path, options) {
      calls.push({ path, ...options })
      return { data: { recorded: true } }
    },
    async get(path) {
      assert.ok(Object.hasOwn(reads, path), `Unexpected backend read: ${path}`)
      readCalls.push({ path, method: 'GET' })
      return reads[path]
    },
  }
}

test('same-origin browser mutations are accepted', () => {
  assert.doesNotThrow(() =>
    assertSameOrigin(
      request({ origin: ORIGIN, 'sec-fetch-site': 'same-origin' }),
    ),
  )
})

test('same-origin validation uses the browser Host when Next reconstructs a different internal URL', () => {
  const browserRequest = new Request(
    'http://localhost:3001/api/workspace/commands',
    {
      method: 'POST',
      headers: {
        host: '127.0.0.1:3001',
        origin: 'http://127.0.0.1:3001',
        'sec-fetch-site': 'same-origin',
      },
    },
  )
  assert.doesNotThrow(() => assertSameOrigin(browserRequest))
  const internalOrigin = new Request(
    'http://localhost:3001/api/workspace/commands',
    {
      method: 'POST',
      headers: { host: '127.0.0.1:3001', origin: 'http://localhost:3001' },
    },
  )
  assert.throws(
    () => assertSameOrigin(internalOrigin),
    errorCode('ORIGIN_FORBIDDEN', 403),
  )
})

test('a configured canonical origin supports reverse proxies without trusting forwarded host headers', () => {
  const previous = process.env.CAREER_KITCHEN_SITE_URL
  try {
    process.env.CAREER_KITCHEN_SITE_URL = ORIGIN
    const proxied = new Request(
      'http://localhost:3001/api/workspace/commands',
      { method: 'POST', headers: { host: 'localhost:3001', origin: ORIGIN } },
    )
    assert.doesNotThrow(() => assertSameOrigin(proxied))
    const forged = new Request('http://localhost:3001/api/workspace/commands', {
      method: 'POST',
      headers: {
        host: 'localhost:3001',
        origin: 'https://attacker.example',
        'x-forwarded-host': 'attacker.example',
        'x-forwarded-proto': 'https',
      },
    })
    assert.throws(
      () => assertSameOrigin(forged),
      errorCode('ORIGIN_FORBIDDEN', 403),
    )
  } finally {
    if (previous === undefined) delete process.env.CAREER_KITCHEN_SITE_URL
    else process.env.CAREER_KITCHEN_SITE_URL = previous
  }
})

test('missing, cross-origin and cross-site mutation origins are rejected', () => {
  for (const headers of [
    {},
    { origin: 'https://attacker.example' },
    { origin: `${ORIGIN}.attacker.example` },
    { origin: ORIGIN, 'sec-fetch-site': 'cross-site' },
    { origin: 'null' },
  ]) {
    assert.throws(
      () => assertSameOrigin(request(headers)),
      errorCode('ORIGIN_FORBIDDEN', 403),
    )
  }
})

test('local auth recognizes only loopback hostnames', () => {
  for (const host of ['localhost', '127.0.0.1', '[::1]', '::1'])
    assert.equal(isLoopbackHost(host), true)
  for (const host of [
    'localhost.attacker.example',
    '127.0.0.1.attacker.example',
    '0.0.0.0',
    'example.com',
    'localhost:3000',
  ])
    assert.equal(isLoopbackHost(host), false)
})

test('API connections support HTTPS and explicit loopback development', () => {
  assert.equal(apiBase(undefined, true), 'http://127.0.0.1:8000')
  assert.equal(apiBase('https://api.example/', false), 'https://api.example')
  assert.equal(apiBase('http://localhost:8000/', true), 'http://localhost:8000')
  assert.equal(apiBase('http://[::1]:8000/', true), 'http://[::1]:8000')
  assert.throws(
    () => apiBase(undefined, false),
    errorCode('API_NOT_CONFIGURED', 503),
  )
})

test('API connections reject credentialed URLs, remote HTTP and URL suffixes', () => {
  for (const url of [
    'https://user:password@api.example',
    'http://api.example',
    'ftp://api.example',
    'https://api.example?token=private',
    'https://api.example#private',
    'http://localhost.attacker.example',
  ]) {
    assert.throws(
      () => apiBase(url, true),
      errorCode('API_NOT_CONFIGURED', 503),
    )
  }
})

test('operation keys preserve a bounded stable idempotency value', () => {
  assert.equal(operationKey(request({ 'Idempotency-Key': KEY })), KEY)
  for (const value of [
    '',
    'short',
    'a'.repeat(129),
    'invalid/key',
    'invalid key',
    'unsafe;key',
  ]) {
    assert.throws(
      () => operationKey(request({ 'Idempotency-Key': value })),
      errorCode('IDEMPOTENCY_KEY_REQUIRED', 422),
    )
  }
})

test('gateway errors retain actionable status without caching', async () => {
  const response = errorResponse(
    new GatewayError(
      412,
      'STALE_VERSION',
      'Refresh and review the current terms.',
    ),
  )
  assert.equal(response.status, 412)
  assert.equal(response.headers.get('cache-control'), 'no-store')
  assert.deepEqual(await response.json(), {
    error: {
      code: 'STALE_VERSION',
      message: 'Refresh and review the current terms.',
    },
  })
})

test('unexpected errors do not expose internal credentials or details', async () => {
  const response = errorResponse(
    new Error('postgresql://private-user:secret@internal-db'),
  )
  assert.equal(response.status, 503)
  const text = await response.text()
  assert.ok(!text.includes('private-user'))
  assert.ok(!text.includes('secret'))
  assert.ok(text.includes('GATEWAY_UNAVAILABLE'))
})

test('commands reject arbitrary actions and non-UUID path parameters', async () => {
  for (const value of ['../../internal', `${ID}?role=ORG_ADMIN`, undefined]) {
    const backend = mockBackend()
    await assert.rejects(
      workspaceCommand(
        backend,
        'vacancy.pause',
        { id: value, expected_version: 3 },
        KEY,
      ),
      errorCode('INVALID_ID', 422),
    )
    assert.equal(backend.calls.length, 0)
  }
  const backend = mockBackend()
  await assert.rejects(
    workspaceCommand(backend, 'internal.grant-admin', {}, KEY),
    errorCode('UNKNOWN_ACTION', 422),
  )
  assert.equal(backend.calls.length, 0)
})

test('versioned changes reject missing, fractional, negative and string versions', async () => {
  for (const expected_version of [undefined, -1, 2.5, '3']) {
    const backend = mockBackend()
    await assert.rejects(
      workspaceCommand(
        backend,
        'vacancy.pause',
        { id: ID, expected_version },
        KEY,
      ),
      errorCode('VERSION_REQUIRED', 422),
    )
    assert.equal(backend.calls.length, 0)
  }
})

test('ordinary organization creation cannot forward verification or role metadata', async () => {
  const backend = mockBackend()
  await workspaceCommand(
    backend,
    'organization.create',
    {
      legal_name: 'Fictional test organization',
      display_name: 'Fictional test',
      domain: 'fictional.example.invalid',
      verification_state: 'VERIFIED',
      role: 'AUTHORIZED_SIGNATORY',
      user_metadata: { role: 'ORG_ADMIN' },
    },
    KEY,
  )
  assert.deepEqual(backend.calls, [
    {
      path: '/v1/organizations',
      method: 'POST',
      body: {
        legal_name: 'Fictional test organization',
        display_name: 'Fictional test',
        domain: 'fictional.example.invalid',
      },
      key: KEY,
    },
  ])
})

test('vacancy edits retain the reviewed version and strip owner overrides', async () => {
  const backend = mockBackend()
  await workspaceCommand(
    backend,
    'vacancy.save',
    {
      id: ID,
      expected_version: 7,
      title: 'Fictional engineering role',
      org_id: OTHER_ID,
      owner_user_id: THIRD_ID,
      state: 'ACTIVE',
      reviewed_by: THIRD_ID,
    },
    KEY,
  )
  assert.deepEqual(backend.calls, [
    {
      path: `/v1/vacancies/${ID}`,
      method: 'PATCH',
      body: {
        title: 'Fictional engineering role',
        org_id: OTHER_ID,
        expected_version: 7,
      },
      key: KEY,
    },
  ])
})

test('team removal uses the DELETE membership route and stable operation key', async () => {
  const backend = mockBackend()
  await workspaceCommand(
    backend,
    'team.revoke',
    { orgId: ID, id: OTHER_ID, expected_version: 4 },
    KEY,
  )
  assert.deepEqual(backend.calls, [
    {
      path: `/v1/organizations/${ID}/members/${OTHER_ID}`,
      method: 'DELETE',
      body: { expected_version: 4 },
      key: KEY,
    },
  ])
})

test('real employment reports use the starts/report route', async () => {
  const backend = mockBackend()
  await workspaceCommand(
    backend,
    'start.report',
    {
      matchId: ID,
      expected_version: 9,
      started_at: '2026-10-16T09:00:00Z',
      source_reference: 'Fictional test start report',
    },
    KEY,
  )
  assert.deepEqual(backend.calls, [
    {
      path: `/v1/matches/${ID}/starts/report`,
      method: 'POST',
      body: {
        expected_version: 9,
        started_at: '2026-10-16T09:00:00Z',
        source_reference: 'Fictional test start report',
      },
      key: KEY,
    },
  ])
})

test('interview scheduling forwards exact proposal and confirmation contracts', async () => {
  const backend = mockBackend()
  const slots = [
    { start_at: '2026-10-25T09:00:00Z', end_at: '2026-10-25T10:00:00Z' },
    { start_at: '2026-10-26T09:00:00Z', end_at: '2026-10-26T10:00:00Z' },
  ]
  await workspaceCommand(
    backend,
    'interview.propose',
    {
      matchId: ID,
      expected_version: 8,
      slots,
      timezone_label: 'America/Los_Angeles',
    },
    KEY,
  )
  await workspaceCommand(
    backend,
    'interview.confirm',
    { matchId: ID, id: OTHER_ID, expected_version: 3, slot_index: 1 },
    KEY,
  )
  assert.deepEqual(backend.calls, [
    {
      path: `/v1/matches/${ID}/interviews/proposals`,
      method: 'POST',
      body: {
        expected_version: 8,
        slots,
        timezone_label: 'America/Los_Angeles',
      },
      key: KEY,
    },
    {
      path: `/v1/matches/${ID}/interviews/${OTHER_ID}/confirm`,
      method: 'POST',
      body: { expected_version: 3, slot_index: 1 },
      key: KEY,
    },
  ])
})

test('decision answers preserve the displayed cycle version and decision token', async () => {
  const backend = mockBackend()
  await workspaceCommand(
    backend,
    'decision.answer',
    {
      id: ID,
      interested: true,
      expected_cycle_version: 7,
      decision_token: 'fictional-decision-token-only',
      role: 'ORG_ADMIN',
    },
    KEY,
  )
  assert.deepEqual(backend.calls, [
    {
      path: `/v1/decisions/${ID}/interested`,
      method: 'POST',
      body: {
        expected_cycle_version: 7,
        decision_token: 'fictional-decision-token-only',
      },
      key: KEY,
    },
  ])
})

test('malformed decision intent cannot silently become a pass', async () => {
  for (const interested of [undefined, 'true', 'false', 0, null]) {
    const backend = mockBackend()
    await assert.rejects(
      workspaceCommand(
        backend,
        'decision.answer',
        {
          id: ID,
          interested,
          expected_cycle_version: 7,
          decision_token: 'fictional-decision-token-only',
        },
        KEY,
      ),
      errorCode('INVALID_DECISION', 422),
    )
    assert.equal(backend.calls.length, 0)
  }
})

test('malformed offer intent cannot silently decline an offer', async () => {
  for (const status of [undefined, 'Accept', 'Decline', null, true]) {
    const backend = mockBackend()
    await assert.rejects(
      workspaceCommand(
        backend,
        'offer.answer',
        { id: ID, expected_version: 3, status },
        KEY,
      ),
      errorCode('INVALID_DECISION', 422),
    )
    assert.equal(backend.calls.length, 0)
  }
})

test('offer creation forwards human affirmation without inventing authority', async () => {
  const backend = mockBackend()
  const terms = 'Fictional test terms; no real employment outcome.'
  await workspaceCommand(
    backend,
    'offer.create',
    {
      matchId: ID,
      expected_version: 5,
      terms,
      expires_at: '2026-10-25T09:00:00Z',
      start_at: '2026-11-02T09:00:00Z',
      affirm_human_authority: false,
      status: 'ACCEPTED',
    },
    KEY,
  )
  assert.deepEqual(backend.calls, [
    {
      path: `/v1/matches/${ID}/offers`,
      method: 'POST',
      body: {
        terms,
        expires_at: '2026-10-25T09:00:00Z',
        start_at: '2026-11-02T09:00:00Z',
        affirm_human_authority: false,
        expected_version: 5,
      },
      key: KEY,
    },
  ])
})

test('policy authorization preserves the exact reviewed scope hash', async () => {
  const backend = mockBackend()
  await workspaceCommand(
    backend,
    'policy.authorize',
    {
      id: ID,
      expected_version: 2,
      scope_hash: 'a'.repeat(64),
      affirm_human_authority: true,
      state: 'AUTHORIZED',
    },
    KEY,
  )
  assert.deepEqual(backend.calls, [
    {
      path: `/v1/pact/policies/${ID}/authorize`,
      method: 'POST',
      body: {
        expected_version: 2,
        scope_hash: 'a'.repeat(64),
        affirm_human_authority: true,
      },
      key: KEY,
    },
  ])
})

test('clarification reads cannot replace the role and requirement versions reviewed by the user', async () => {
  const backend = mockBackend({
    [`/v1/vacancies/${ID}`]: {
      id: ID,
      version: 99,
      terms_hash: 'new-terms',
      requirements: [{ id: OTHER_ID, version: 80 }],
    },
  })
  await workspaceCommand(
    backend,
    'clarification.create',
    {
      vacancyId: ID,
      expected_version: 6,
      terms_hash: 'reviewed-terms',
      requirementId: OTHER_ID,
      requirement_expected_version: 4,
      proposed_text: 'Fictional clarified preference',
      reason: 'Fictional test clarification reason',
      expires_at: '2026-10-20T09:00:00Z',
    },
    KEY,
  )
  assert.equal(backend.calls[0].body.expected_version, 6)
  assert.equal(backend.calls[0].body.requirement_expected_version, 4)
  assert.equal(backend.calls[0].body.terms_hash, 'reviewed-terms')
})

test('evidence consent derives the organization from the scoped vacancy', async () => {
  const backend = mockBackend({
    [`/v1/vacancies/${ID}`]: {
      id: ID,
      org_id: OTHER_ID,
      version: 99,
      terms_hash: 'new-terms',
    },
  })
  await workspaceCommand(
    backend,
    'consent.evidence',
    {
      vacancyId: ID,
      expected_version: 6,
      terms_hash: 'reviewed-terms',
      claimId: THIRD_ID,
      claim_expected_version: 3,
      org_id: THIRD_ID,
      kind: 'DISCLOSE_SUMMARY',
      consent_text: 'Fictional explicit evidence consent',
      expires_at: '2026-10-20T09:00:00Z',
      checkbox_confirmed: true,
    },
    KEY,
  )
  assert.equal(backend.calls[0].path, '/v1/consents/evidence')
  assert.equal(backend.calls[0].body.org_id, OTHER_ID)
  assert.equal(backend.calls[0].body.expected_version, 6)
  assert.equal(backend.calls[0].body.claim_expected_version, 3)
  assert.equal(backend.calls[0].body.terms_hash, 'reviewed-terms')
})

test('candidate partial edits retain the reviewed version and existing consent fields', async () => {
  const backend = mockBackend({
    '/v1/candidates/me': {
      version: 99,
      headline: 'Fictional previous role',
      region: 'Seattle',
      role_families: ['ENGINEERING'],
      cap: 3,
      terms_accepted: true,
      privacy_accepted: true,
      profile_confirmed: true,
    },
  })
  await workspaceCommand(
    backend,
    'candidate.save',
    {
      expected_version: 7,
      profile: {
        version: 7,
        headline: 'Fictional reviewed role',
        region: 'Seattle',
        role_families: ['ENGINEERING'],
        cap: 3,
        terms_accepted: true,
        privacy_accepted: true,
      },
      patch: {
        title: 'Fictional updated role',
        user_id: THIRD_ID,
        state: 'ACTIVE',
      },
    },
    KEY,
  )
  const mutation = backend.calls[0]
  assert.equal(mutation.method, 'PUT')
  assert.equal(mutation.body.expected_version, 7)
  assert.equal(mutation.body.headline, 'Fictional updated role')
  assert.equal(mutation.body.terms_accepted, true)
  assert.equal(mutation.body.privacy_accepted, true)
  assert.equal(
    backend.readCalls.length,
    0,
    'Retries must retain the reviewed snapshot instead of reading newer profile values',
  )
  assert.equal(Object.hasOwn(mutation.body, 'user_id'), false)
  assert.equal(Object.hasOwn(mutation.body, 'state'), false)
})

test('every supported workspace command targets a method in the published OpenAPI contract', async () => {
  const schema = JSON.parse(
    readFileSync(new URL('../docs/openapi.json', import.meta.url), 'utf8'),
  )
  const reads = {
    '/v1/candidates/me': {
      cap: 3,
      currency: 'USD',
      compensation_floor: null,
      compensation_period: 'ANNUAL',
      employment_types: ['FULL_TIME'],
      work_modes: ['REMOTE'],
      locations: ['Seattle'],
    },
    '/v1/candidates/me/skills': [
      { id: ID, name: 'fictional_skill', version: 3 },
    ],
    [`/v1/vacancies/${ID}`]: {
      id: ID,
      org_id: OTHER_ID,
      terms_hash: 'a'.repeat(64),
      requirements: [{ id: OTHER_ID, version: 2 }],
    },
    [`/v1/pact/policies/${ID}`]: { id: ID },
    '/v1/privacy/export': { operation_id: ID },
  }
  const common = {
    id: ID,
    matchId: ID,
    orgId: ID,
    vacancyId: ID,
    requirementId: OTHER_ID,
    claimId: THIRD_ID,
    expected_version: 3,
    terms_hash: 'a'.repeat(64),
    expected_cycle_version: 4,
    decision_token: 'fictional-decision-token-only',
  }
  const actions = [
    ['candidate.save', {}],
    ['candidate.preferences', {}],
    ['candidate.activate', {}],
    ['candidate.pause', {}],
    ['candidate.skill.add', { name: 'fictional_skill' }],
    ['candidate.skill.remove', {}],
    ['decision.answer', { interested: true }],
    ['decision.answer', { interested: false }],
    ['offer.answer', { status: 'Accepted' }],
    ['offer.answer', { status: 'Declined' }],
    ['offer.create', {}],
    ['start.report', {}],
    ['message.send', {}],
    ['interview.propose', {}],
    ['interview.confirm', {}],
    ['stage.update', {}],
    ['notification.read', {}],
    ['notifications.preferences', {}],
    ['privacy.export', {}],
    ['privacy.export.status', {}],
    ['privacy.delete', {}],
    ['organization.create', {}],
    ['organization.save', {}],
    ['team.invite', {}],
    ['team.accept', {}],
    ['team.update', {}],
    ['team.revoke', {}],
    ['vacancy.create', {}],
    ['vacancy.save', {}],
    ['vacancy.activate', {}],
    ['vacancy.pause', {}],
    ['vacancy.close', {}],
    ['requirement.create', {}],
    ['policy.create', {}],
    ['policy.authorize', {}],
    ['policy.revoke', {}],
    ['policy.load', {}],
    ['clarification.create', {}],
    ['clarification.respond', {}],
    ['research.replan', {}],
    ['evidence.create', {}],
    ['evidence.revoke', {}],
    ['consent.revoke', {}],
    ['consent.terms', {}],
    ['consent.evidence', {}],
  ]
  for (const [action, values] of actions) {
    const backend = mockBackend(reads)
    await workspaceCommand(backend, action, { ...common, ...values }, KEY)
    const routes = [...backend.calls, ...backend.readCalls]
    assert.ok(routes.length > 0, `${action} must contact an API route`)
    for (const route of routes) {
      const path = Object.keys(schema.paths).find((pattern) =>
        new RegExp(`^${pattern.replace(/\{[^}]+\}/g, '[^/]+')}$`).test(
          route.path,
        ),
      )
      assert.ok(path, `${action} references missing API path ${route.path}`)
      assert.ok(
        schema.paths[path][route.method.toLowerCase()],
        `${action} references unsupported method ${route.method} ${path}`,
      )
    }
  }
})
