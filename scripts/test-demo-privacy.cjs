/* Demo-only privacy regressions. All people and amounts are synthetic fixtures. */
const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

function demoModules() {
  const cache = new Map()
  const timers = []
  let latest
  const wrapper = ({ children }) => React.createElement('div', null, children)
  const stubs = {
    swr: {
      __esModule: true,
      default: () => ({ data: latest }),
      mutate: (_key, value) => { latest = value; return Promise.resolve(value) },
    },
    '@/components/ui/sheet': Object.fromEntries(['Sheet', 'SheetContent', 'SheetDescription', 'SheetTitle'].map((name) => [name, wrapper])),
  }

  function load(relative) {
    const filename = path.resolve(__dirname, '..', relative)
    if (cache.has(filename)) return cache.get(filename).exports
    const loaded = { exports: {} }
    cache.set(filename, loaded)
    const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText
    const nodeRequire = createRequire(filename)
    function scopedRequire(request) {
      if (stubs[request]) return stubs[request]
      if (request.startsWith('@/') || request.startsWith('.')) {
        const target = request.startsWith('@/')
          ? path.resolve(__dirname, '..', request.slice(2))
          : path.resolve(path.dirname(filename), request)
        const source = [target, target + '.ts', target + '.tsx'].find((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile())
        if (source && /\.tsx?$/.test(source)) return load(path.relative(path.resolve(__dirname, '..'), source))
      }
      return nodeRequire(request)
    }
    new Function('require', 'module', 'exports', 'window', code)(scopedRequire, loaded, loaded.exports, { setTimeout: (callback) => timers.push(callback), clearTimeout() {} })
    return loaded.exports
  }

  return { load, timers, state: () => latest }
}

test('public compensation explanations preserve incompatibility without exposing the exact minimum', () => {
  const { load } = demoModules()
  const { evaluate, freshPassState } = load('lib/demo/pass.ts')
  const state = freshPassState()
  const candidate = state.candidates.find((person) => person.id === 'pc5')
  const evaluation = evaluate(state.order, candidate)
  assert.equal(evaluation.terms.floor, 'conflict')
  assert.equal(evaluation.verdict, 'held')
  const publicExplanation = JSON.stringify({ conflicts: evaluation.conflicts, uncertainties: evaluation.uncertainties, terms: evaluation.terms })
  assert.doesNotMatch(publicExplanation, /190|\$190k|Floor \$/)
  assert.match(publicExplanation, /minimum stays private/)
  assert.equal(candidate.floor.value, 190, 'synthetic private input remains available to the demo evaluator')
})
test('employer tickets and inspectors show alignment while masking every known fixture minimum', () => {
  const { load } = demoModules()
  const { evaluate, freshPassState } = load('lib/demo/pass.ts')
  const { CandidateTicket } = load('components/pass/candidate-ticket.tsx')
  const { Inspector } = load('components/pass/inspector.tsx')
  const state = freshPassState()
  for (const candidate of state.candidates) {
    const ticket = renderToStaticMarkup(React.createElement(CandidateTicket, {
      ev: evaluate(state.order, candidate), order: state.order, index: 0,
      suggested: true, pendingTests: 0, onInspect() {},
    }))
    const inspector = renderToStaticMarkup(React.createElement(Inspector, {
      state, candidateId: candidate.id, onClose() {},
    }))
    for (const html of [ticket, inspector]) {
      assert.match(html, /exact minimum stays private/)
      if (candidate.floor.value !== null) assert.ok(!html.includes('$' + candidate.floor.value + 'k'), candidate.name + ' exact minimum must stay hidden')
    }
    assert.ok(inspector.includes('$' + state.order.ceiling + 'k'), 'employer may still see their own ceiling')
  }
})

test('compensation questions ask about budget compatibility instead of requesting an exact minimum', () => {
  const { load } = demoModules()
  const { freshPassState } = load('lib/demo/pass.ts')
  const { Inspector } = load('components/pass/inspector.tsx')
  const state = freshPassState()
  const candidate = state.candidates.find((person) => person.id === 'pc2')
  for (const signal of Object.values(candidate.signals)) { signal.status = 'confirmed'; signal.meets = true }
  const html = renderToStaticMarkup(React.createElement(Inspector, { state, candidateId: candidate.id, onClose() {} }))
  assert.match(html, /Would the advertised base salary budget/)
  assert.match(html, /Your exact minimum stays private/)
  assert.doesNotMatch(html, /share the base salary floor/)
})

test('scripted compensation replies update matching without disclosing amounts in public reply and log text', () => {
  const modules = demoModules()
  const { passActions, evaluate } = modules.load('lib/demo/pass.ts')
  assert.equal(passActions.sendTasteTest('pc2', 'floor', 'Compensation alignment', 'Would this advertised budget meet your expectations?'), true)
  assert.equal(modules.timers.length, 1)
  modules.timers[0]()
  const state = modules.state()
  const candidate = state.candidates.find((person) => person.id === 'pc2')
  assert.equal(candidate.floor.value, 160)
  assert.equal(candidate.floor.status, 'confirmed')
  assert.equal(evaluate(state.order, candidate).terms.floor, 'fits')
  assert.equal(state.tasteTests[0].status, 'Answered')
  const publicText = JSON.stringify({
    replies: state.tasteTests.map(({ question, answer, topic }) => ({ question, answer, topic })),
    log: state.log.map((entry) => entry.text),
  })
  assert.doesNotMatch(publicText, /160|\$160k|My floor/)
  assert.match(publicText, /confirmed privately/)
})

