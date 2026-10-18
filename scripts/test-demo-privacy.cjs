/* Connected employer privacy regressions. All records and amounts are synthetic. */
const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const root = path.resolve(__dirname, '..')
const privateProfile = {
  compensation_floor: '187654.32',
  undisclosed_evidence: 'private-evidence-sentinel',
}

function connectedModules() {
  const cache = new Map()
  let workspace
  // Render all dialog/sheet children, including profile details normally hidden
  // until opened. These stubs do not replace the real cards or state projection.
  const wrapper = ({ children }) => React.createElement('div', null, children)
  const stubs = {
    'server-only': {},
    '@/lib/workspace': {
      useWorkspace: () => ({
        data: workspace,
        execute: () => assert.fail('Rendering must not mutate the workspace'),
      }),
    },
    '@/components/brand': {
      CompanyMark: ({ name }) => React.createElement('span', null, name),
    },
    '@/components/workspace/kit': {
      SectionTitle: ({ title }) => React.createElement('h2', null, title),
      EmptyNote: ({ title, description }) => React.createElement('p', null, title, description),
    },
  }

  function load(relative) {
    const filename = path.resolve(root, relative)
    if (cache.has(filename)) return cache.get(filename).exports
    const loaded = { exports: {} }
    cache.set(filename, loaded)
    const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
        esModuleInterop: true,
      },
      fileName: filename,
    }).outputText
    const nodeRequire = createRequire(filename)
    function scopedRequire(request) {
      if (Object.hasOwn(stubs, request)) return stubs[request]
      if (request.startsWith('@/components/ui/')) {
        return new Proxy({}, { get: (_target, name) => name === '__esModule' ? true : wrapper })
      }
      if (request.startsWith('@/') || request.startsWith('.')) {
        const target = request.startsWith('@/')
          ? path.resolve(root, request.slice(2))
          : path.resolve(path.dirname(filename), request)
        const source = [target, target + '.ts', target + '.tsx'].find(
          (candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile(),
        )
        if (source && /\.tsx?$/.test(source)) return load(path.relative(root, source))
      }
      return nodeRequire(request)
    }
    new Function('require', 'module', 'exports', code)(scopedRequire, loaded, loaded.exports)
    return loaded.exports
  }

  return { load, setWorkspace: (state) => { workspace = state } }
}

function authorizedBackend({ aligned = true, disclosed = true } = {}) {
  const vacancy = {
    id: 'vacancy-authorized', org_id: 'organization-authorized', version: 3,
    title: 'Product Designer', description: 'Build accessible product experiences.',
    organization_name: 'Example Studio', state: 'ACTIVE', terms_hash: 'terms-v3',
    pay_min: '101000', pay_max: '153000', currency: 'USD', compensation_period: 'ANNUAL',
    work_mode: 'HYBRID', employment_type: 'FULL_TIME', location_region: 'New York',
    cap: 3, deadline_at: '2099-01-01T12:00:00Z', requirements: [],
  }
  const candidate = {
    id: 'candidate-authorized', headline: 'Accessible product designer',
    summary: 'Designs accessible workflows and component libraries.', region: 'New York',
    skills: ['Accessibility'], compensation_aligned: aligned,
    experiences: [{ title: 'Designer', organization_label: 'Disclosed Studio', details: 'Built a component library.' }],
    education: [{ qualification: 'Design certificate', institution: 'Disclosed School' }],
  }
  const card = {
    id: 'decision-authorized', status: 'ACTIVE', version: 1, cycle_version: 2,
    decision_token: 'authorized-decision-token', other_side_interested: true,
    expires_at: '2099-01-01T12:00:00Z', vacancy,
    candidate: disclosed ? candidate : null,
  }
  const records = new Map([
    ['/v1/sessions/me', { id: 'employer-user', email: 'employer@example.invalid', memberships: [] }],
    ['/v1/candidates/me', null],
    ['/v1/organizations', [{ id: vacancy.org_id, display_name: 'Example Studio', legal_name: 'Example Studio LLC', verification_state: 'VERIFIED' }]],
    ['/v1/notifications/preferences', { version: 1, email_opt_in: false, in_app_opt_in: true, quiet_hours: {} }],
    ['/v1/notifications', []],
    ['/v1/privacy/export', null],
    [`/v1/organizations/${vacancy.org_id}/vacancies`, [vacancy]],
    [`/v1/organizations/${vacancy.org_id}/pact/policies`, []],
    [`/v1/organizations/${vacancy.org_id}/members`, []],
    [`/v1/vacancies/${vacancy.id}/decisions`, { data: [card], capacity: { used: 1, maximum: 3 } }],
    [`/v1/vacancies/${vacancy.id}/pipeline`, []],
    [`/v1/vacancies/${vacancy.id}/pact/clarifications`, []],
    [`/v1/vacancies/${vacancy.id}/shortlist/status`, null],
  ])
  const calls = []
  async function read(endpoint) {
    calls.push(endpoint)
    assert.ok(records.has(endpoint), `Unexpected or private employer request: ${endpoint}`)
    return records.get(endpoint)
  }
  return { api: { get: read, optional: read, all: read, request: read }, calls, card, vacancy }
}

function assertPrivateValuesAbsent(value) {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  for (const secret of Object.values(privateProfile)) assert.ok(!text.includes(secret), `Private value disclosed: ${secret}`)
  assert.doesNotMatch(text, /187,654\.32|compensation_floor|undisclosed_evidence/)
}

test('employer workspace serializes only authorized candidate summaries, never private profile or evidence requests', async () => {
  const modules = connectedModules()
  const { workspaceState } = modules.load('lib/server/workspace-state.ts')
  for (const aligned of [true, false]) {
    const { api, calls } = authorizedBackend({ aligned })
    const workspace = await workspaceState(api, 'employer', 'supabase')
    assert.equal(workspace.candidates.length, 1)
    assert.equal(workspace.candidates[0].compensation, 'Private')
    assert.equal(workspace.backend.employerDecisions[0].candidate.compensation_aligned, aligned)
    assert.equal(workspace.backend.candidate, null)
    assert.deepEqual(workspace.evidence, [])
    assertPrivateValuesAbsent(workspace)
    assert.ok(calls.includes('/v1/vacancies/vacancy-authorized/decisions'))
    assert.ok(!calls.some((endpoint) => endpoint.startsWith('/v1/evidence/') || endpoint.includes('/candidates/candidate-authorized')))
  }
})

test('connected Pass cards and disclosed profile details show alignment and employer budget without a private minimum', async () => {
  const modules = connectedModules()
  const { workspaceState } = modules.load('lib/server/workspace-state.ts')
  const { PassBoard } = modules.load('components/pass/pass-board.tsx')
  for (const aligned of [true, false]) {
    const { api, card } = authorizedBackend({ aligned })
    const workspace = await workspaceState(api, 'employer', 'supabase')
    // Defense in depth in the UI: even an unexpected private API field must not
    // be rendered by the ticket or the expanded disclosed-profile details.
    card.candidate.compensation_floor = privateProfile.compensation_floor
    modules.setWorkspace(workspace)
    const html = renderToStaticMarkup(React.createElement(PassBoard))
    assert.match(html, aligned ? /Compensation range aligned/ : /Compensation alignment needs review/)
    assert.match(html, /101,000/)
    assert.match(html, /153,000/)
    assert.match(html, /Disclosed Studio/)
    assert.match(html, /Disclosed School/)
    assert.match(html, /Private compensation floors and undisclosed evidence are unavailable/)
    assertPrivateValuesAbsent(html)
  }
})

test('connected candidate summaries keep compensation private even if a view model contains an exact minimum', async () => {
  const modules = connectedModules()
  const { workspaceState } = modules.load('lib/server/workspace-state.ts')
  const { CandidateCard } = modules.load('components/workspace/opportunities.tsx')
  const { api } = authorizedBackend()
  const workspace = await workspaceState(api, 'employer', 'supabase')
  modules.setWorkspace(workspace)
  const html = renderToStaticMarkup(React.createElement(CandidateCard, {
    candidate: { ...workspace.candidates[0], compensation: privateProfile.compensation_floor },
  }))
  assert.match(html, /Accessible product designer/)
  assert.match(html, /For Product Designer/)
  assert.match(html, /Private compensation expectations are never displayed/)
  assert.match(html, /self-reported/)
  assertPrivateValuesAbsent(html)
})

test('an undisclosed candidate stays absent from workspace summaries and Pass profile details', async () => {
  const modules = connectedModules()
  const { workspaceState } = modules.load('lib/server/workspace-state.ts')
  const { PassBoard } = modules.load('components/pass/pass-board.tsx')
  const { api } = authorizedBackend({ disclosed: false })
  const workspace = await workspaceState(api, 'employer', 'supabase')
  assert.deepEqual(workspace.candidates, [])
  assertPrivateValuesAbsent(workspace)
  modules.setWorkspace(workspace)
  const html = renderToStaticMarkup(React.createElement(PassBoard))
  assert.match(html, /Candidate introduction/)
  assert.doesNotMatch(html, /Accessible product designer|Disclosed Studio|Disclosed School|Review disclosed profile/)
  assertPrivateValuesAbsent(html)
})
