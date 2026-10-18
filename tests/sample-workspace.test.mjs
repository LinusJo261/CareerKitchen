import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import ts from 'typescript'

const cache = new Map()
function load(url) {
  const filename = fileURLToPath(url)
  if (cache.has(filename)) return cache.get(filename).exports
  const module = { exports: {} }
  cache.set(filename, module)
  const code = ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const native = createRequire(url)
  new Function('require', 'module', 'exports', code)(
    (name) => name.startsWith('.') ? load(new URL(name + '.ts', url)) : native(name),
    module, module.exports,
  )
  return module.exports
}
const { workspaceState } = load(new URL('../lib/server/workspace-state.ts', import.meta.url))
const { workspaceCommand } = load(new URL('../lib/server/workspace-commands.ts', import.meta.url))

test('sample employer workspace loads one demonstration scope rather than every sample vacancy', async () => {
  const organizations = Array.from({ length: 200 }, (_, index) => ({
    id: 'organization-' + index, display_name: 'Synthetic company ' + index,
    legal_name: 'Synthetic company ' + index, verification_state: 'VERIFIED', version: 2,
  }))
  const jobs = Array.from({ length: 100 }, (_, index) => ({
    id: 'vacancy-' + index, org_id: organizations[0].id, version: 2, title: 'Synthetic role',
    description: 'Fictional sample vacancy', requirements: [], pay_min: '0', pay_max: '0',
    currency: 'USD', compensation_period: 'ANNUAL', work_mode: 'REMOTE',
    employment_type: 'FULL_TIME', cap: 3, state: 'ACTIVE',
  }))
  const status = { ready: true, candidates: 20000, vacancies: 20000, organizations: 200,
    organization_id: organizations[0].id, vacancy_ids: jobs.slice(0, 4).map((job) => job.id) }
  const calls = []
  async function read(path) {
    calls.push(path)
    if (path === '/v1/demo/status') return status
    if (path === '/v1/sessions/me') return { id: 'sample-employer', email: 'employer@samples.example.invalid', memberships: [] }
    if (path === '/v1/candidates/me' || path === '/v1/privacy/export') return null
    if (path === '/v1/organizations') return organizations
    if (path === '/v1/notifications/preferences') return { version: 1, quiet_hours: {}, in_app_opt_in: true }
    if (path === '/v1/notifications') return []
    if (path === '/v1/organizations/organization-0/vacancies') return jobs
    if (path === '/v1/organizations/organization-0/pact/policies' || path === '/v1/organizations/organization-0/members') return []
    assert.match(path, /^\/v1\/vacancies\/vacancy-[0-3]\/(decisions|pipeline|pact\/clarifications|shortlist\/status)$/)
    if (path.endsWith('/decisions')) return { data: [], capacity: { used: 0, maximum: 3 } }
    return path.endsWith('/status') ? null : []
  }
  const api = { get: read, optional: read, all: read, request: read }
  const state = await workspaceState(api, 'employer', 'sample')
  assert.equal(state.context.mode, 'sample')
  assert.equal(state.context.sampleDemo.candidates, 20000)
  assert.equal(state.backend.organizations.length, 1)
  assert.equal(state.backend.vacancies.length, 4)
  assert.ok(calls.length < 35)
  assert.ok(!calls.some((path) => /organization-(?:[1-9]\d*)\//.test(path)))
})

test('matching demonstration cannot be dispatched to the ordinary backend', async () => {
  let sent = false
  await assert.rejects(workspaceCommand({ mode: 'standard', request() { sent = true } }, 'demo.reconcile', {}, 'sample-test-key'),
    (error) => error.status === 403 && error.code === 'DEMO_ONLY')
  assert.equal(sent, false)
  const result = await workspaceCommand({ mode: 'sample', async request(path, options) {
    assert.equal(path, '/v1/demo/reconcile')
    assert.deepEqual(options, { method: 'POST', body: {}, key: 'sample-test-key' })
    return { data: { synthetic: true, issued_count: 3 } }
  } }, 'demo.reconcile', {}, 'sample-test-key')
  assert.equal(result.issued_count, 3)
})
