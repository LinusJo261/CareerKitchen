/** Real HTTP check using only explicit local fictional accounts; never resets data. */
import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'

const base = new URL(process.env.FRONTEND_SMOKE_URL || 'http://127.0.0.1:3000')
assert(
  ['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname),
  'Frontend smoke is restricted to loopback',
)
const config = await (await fetch(new URL('/api/auth/config', base))).json()
assert.equal(
  config.mode,
  'local',
  'Enable FRONTEND_LOCAL_DEMO and run the fictional demo API before this check',
)
const request = async (path, options = {}) => {
  const { cookie, body, key, origin = base.origin, ...rest } = options
  const response = await fetch(new URL(path, base), {
    ...rest,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(cookie ? { Cookie: cookie } : {}),
      ...(key ? { 'Idempotency-Key': key } : {}),
      Origin: origin,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  return { response, payload: await response.json() }
}
async function signIn(account) {
  const result = await request('/api/auth/session', {
    method: 'POST',
    body: { account, role: account === 'employer' ? 'employer' : 'candidate' },
  })
  assert.equal(result.response.status, 200, JSON.stringify(result.payload))
  const cookies = result.response.headers.getSetCookie()
  assert(cookies.some((x) => /HttpOnly/i.test(x)))
  assert(!JSON.stringify(result.payload).includes('access_token'))
  return cookies.map((x) => x.split(';')[0]).join('; ')
}
async function command(cookie, action, payload, key = randomUUID()) {
  return request('/api/workspace/commands', {
    method: 'POST',
    cookie,
    body: { action, payload },
    key,
  })
}
const blocked = await request('/api/auth/session', {
  method: 'POST',
  body: { account: 'employer' },
  origin: 'https://unrelated.example.invalid',
})
assert.equal(blocked.response.status, 403)
const candidate = await signIn('candidate-30')
const initial = await request('/api/workspace?role=candidate', {
  cookie: candidate,
})
assert.equal(initial.response.status, 200, JSON.stringify(initial.payload))
const original = initial.payload.backend.candidate
assert(original?.id && original.version)
const summary = `${original.summary}\nFictional full-stack smoke check.`
const key = randomUUID(),
  patch = {
    patch: { summary },
    profile: original,
    expected_version: original.version,
  }
let savedVersion
try {
  const malformed = await command(candidate, 'decision.answer', {
    id: randomUUID(),
    expected_cycle_version: 1,
    decision_token: 'fictional-token-unused',
  })
  assert.equal(malformed.response.status, 422)
  const saved = await command(candidate, 'candidate.save', patch, key)
  assert.equal(saved.response.status, 200, JSON.stringify(saved.payload))
  savedVersion = saved.payload.data.version
  assert.equal(savedVersion, original.version + 1)
  const replay = await command(candidate, 'candidate.save', patch, key)
  assert.equal(replay.response.status, 200, JSON.stringify(replay.payload))
  assert.equal(replay.payload.data.version, savedVersion)
  const stale = await command(candidate, 'candidate.save', {
    patch: { summary: original.summary },
    profile: original,
    expected_version: original.version,
  })
  assert.equal(stale.response.status, 412, JSON.stringify(stale.payload))
  const reloaded = await request('/api/workspace?role=candidate', {
    cookie: candidate,
  })
  assert.equal(reloaded.response.status, 200)
  assert.equal(reloaded.payload.profile.summary, summary)
} finally {
  if (savedVersion) {
    const restored = await command(candidate, 'candidate.save', {
      patch: { summary: original.summary },
      profile: original,
      expected_version: savedVersion,
    })
    assert.equal(
      restored.response.status,
      200,
      'Could not restore fictional profile summary',
    )
  }
}
const employer = await signIn('employer')
const workspace = await request('/api/workspace?role=employer', {
  cookie: employer,
})
assert.equal(workspace.response.status, 200, JSON.stringify(workspace.payload))
assert(workspace.payload.backend.vacancies.length > 0)
assert(workspace.payload.backend.memberships.every((x) => x.org_id))
assert(workspace.payload.candidates.every((x) => x.compensation === 'Private'))
const logout = await request('/api/auth/logout', {
  method: 'POST',
  cookie: candidate,
})
assert.equal(logout.response.status, 200)
const revoked = await request('/api/workspace?role=candidate', {
  cookie: candidate,
})
assert.equal(revoked.response.status, 401)
const logoutRetry = await request('/api/auth/logout', {
  method: 'POST',
  cookie: candidate,
})
assert.equal(logoutRetry.response.status, 200)
await request('/api/auth/logout', { method: 'POST', cookie: employer })
console.log(
  'PASS: real frontend → BFF → FastAPI → PostgreSQL; local sign-in, CSRF, persistent save/restore, exact retry, stale version, scoped employer data and session revocation',
)
