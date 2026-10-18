'use client'
// Demo engine for The Pass. Every person and record is fictional. Evaluation here
// mirrors what the backend allocator would return; replace `usePass` with an HTTP
// adapter when the FastAPI endpoints exist. Allocation order is advisory only.
import useSWR, { mutate as globalMutate } from 'swr'
import type { Arrangement, PassCandidate, PassOrder, PassState, Provenance, RecipeWeight, Signal } from '@/lib/contracts'

export const SERVICE_LIMIT = 4
const KEY = 'career-kitchen-pass'

const s = (status: Provenance, meets: boolean, note: string, evidence?: string): Signal => ({ status, meets, note, evidence })

const initialOrder: PassOrder = {
  id: 'ord-0412',
  vacancyId: 'v1',
  ticket: '0412',
  title: 'Senior Product Designer',
  company: 'Forma',
  arrangement: 'Hybrid · NYC 2 days',
  ceiling: 175,
  verificationBudget: 3,
  recipe: [
    { id: 'systems', label: 'Has led a design system', weight: 'must' },
    { id: 'b2b', label: 'B2B SaaS product work', weight: 'must' },
    { id: 'research', label: 'Runs their own research', weight: 'nice' },
    { id: 'code', label: 'Prototypes in code', weight: 'nice' },
    { id: 'mentoring', label: 'Has mentored designers', weight: 'off' },
  ],
}

const candidates: PassCandidate[] = [
  {
    id: 'pc1', ticket: 'A', name: 'Jamie Chen', title: 'Senior Product Designer', location: 'New York, NY', years: 7, allocationRank: 1,
    summary: 'Systems-minded designer who makes dense workflows feel calm. Led the component library at a mid-size analytics company.',
    signals: {
      systems: s('confirmed', true, 'Led a 140-component library', 'Portfolio case study'),
      b2b: s('confirmed', true, 'Five years on analytics tools'),
      research: s('inferred', true, 'Case studies cite interviews they ran'),
      code: s('unknown', false, 'Not mentioned anywhere'),
      mentoring: s('confirmed', true, 'Managed two designers'),
    },
    arrangement: { value: 'Hybrid', status: 'confirmed' },
    floor: { value: 165, status: 'confirmed' },
    priorities: ['A design-led team under 40 people', 'Ownership of a core surface', 'Hybrid, not fully on-site'],
    questions: ['How much of the design system is already in production?'],
    evidence: [
      { label: 'Employment history, 2018–present', issuer: 'Attested by prior employer', status: 'Verified' },
      { label: 'Design system case study', issuer: 'Portfolio', status: 'Self-reported' },
    ],
  },
  {
    id: 'pc2', ticket: 'B', name: 'Sam Rivera', title: 'Senior Product Designer', location: 'Brooklyn, NY', years: 6, allocationRank: 2,
    summary: 'Builds useful tools for people at work. Strong craft, comfortable owning a surface end to end.',
    signals: {
      systems: s('confirmed', true, 'Co-led tokens migration', 'Reference from engineering lead'),
      b2b: s('confirmed', true, 'Collaboration software, four years'),
      research: s('unknown', false, 'No research work shown'),
      code: s('inferred', true, 'Links to a React prototype repo'),
      mentoring: s('inferred', false, 'No direct reports listed'),
    },
    arrangement: { value: 'Either', status: 'inferred' },
    floor: { value: null, status: 'unknown' },
    priorities: ['Working closely with engineering', 'Clear product direction', 'Start within two weeks'],
    questions: ['Who would I report to?', 'Is the role open to a four-day week?'],
    evidence: [{ label: 'Engineering lead reference', issuer: 'Reference check', status: 'Verified' }],
  },
  {
    id: 'pc3', ticket: 'C', name: 'Priya Natarajan', title: 'Lead Product Designer', location: 'Philadelphia, PA', years: 9, allocationRank: 3,
    summary: 'Research-led lead designer. Built a design system and the research practice at a payroll startup.',
    signals: {
      systems: s('inferred', true, 'Title history suggests system ownership'),
      b2b: s('confirmed', true, 'Payroll and HR software'),
      research: s('confirmed', true, 'Founded the research practice', 'Published research guide'),
      code: s('confirmed', true, 'Ships prototypes in SwiftUI'),
      mentoring: s('confirmed', true, 'Managed a team of four'),
    },
    arrangement: { value: 'Remote only', status: 'confirmed' },
    floor: { value: 170, status: 'confirmed' },
    priorities: ['Fully remote', 'Influence on research practice', 'Senior peers to learn from'],
    questions: ['Would the team consider remote for the right person?'],
    evidence: [
      { label: 'Employment history, 2015–present', issuer: 'Attested by prior employer', status: 'Verified' },
      { label: 'Published research guide', issuer: 'Public link', status: 'Self-reported' },
    ],
  },
  {
    id: 'pc4', ticket: 'D', name: 'Taylor Brooks', title: 'Product Designer', location: 'Austin, TX', years: 5, allocationRank: 4,
    summary: 'Research-driven designer focused on inclusive experiences. Mostly consumer work, some internal tools.',
    signals: {
      systems: s('unknown', false, 'Contributed to a system; ownership unclear'),
      b2b: s('inferred', false, 'Background is mostly consumer apps'),
      research: s('confirmed', true, 'Ran a 30-participant accessibility study'),
      code: s('confirmed', true, 'Builds prototypes in Framer'),
      mentoring: s('unknown', false, 'Not mentioned'),
    },
    arrangement: { value: 'Remote only', status: 'inferred' },
    floor: { value: 150, status: 'confirmed' },
    priorities: ['Accessible products', 'A team that values research', 'Remote-friendly'],
    questions: ['How does the team measure design quality?'],
    evidence: [{ label: 'Accessibility study report', issuer: 'Portfolio', status: 'Self-reported' }],
  },
  {
    id: 'pc5', ticket: 'E', name: 'Dev Okafor', title: 'Staff Product Designer', location: 'Jersey City, NJ', years: 11, allocationRank: 5,
    summary: 'Staff-level designer who has built two design systems from scratch at enterprise companies.',
    signals: {
      systems: s('confirmed', true, 'Built two systems from scratch', 'Attested by prior employer'),
      b2b: s('confirmed', true, 'Enterprise procurement software'),
      research: s('inferred', true, 'Leads discovery sprints'),
      code: s('unknown', false, 'Not mentioned'),
      mentoring: s('confirmed', true, 'Mentors through a design guild'),
    },
    arrangement: { value: 'Hybrid', status: 'confirmed' },
    floor: { value: 190, status: 'confirmed' },
    priorities: ['Staff-level scope', 'Compensation at senior-staff band', 'Shorter commute days'],
    questions: ['Is there a staff track for designers?'],
    evidence: [{ label: 'Design system leadership', issuer: 'Attested by prior employer', status: 'Verified' }],
  },
  {
    id: 'pc6', ticket: 'F', name: 'Lena Fischer', title: 'Senior Product Designer', location: 'Queens, NY', years: 6, allocationRank: 6,
    summary: 'Detail-oriented designer who cares about information density. Recently maintained a system for a CRM.',
    signals: {
      systems: s('confirmed', true, 'Maintained CRM design system'),
      b2b: s('inferred', true, 'CRM work implies B2B'),
      research: s('confirmed', true, 'Weekly customer calls'),
      code: s('unknown', false, 'Not mentioned'),
      mentoring: s('unknown', false, 'Not mentioned'),
    },
    arrangement: { value: 'Hybrid', status: 'confirmed' },
    floor: { value: null, status: 'unknown' },
    priorities: ['Stable, well-funded team', 'Hybrid near Queens', 'Craft over speed'],
    questions: ['What does the first 90 days look like?'],
    evidence: [{ label: 'Employment history, 2019–present', issuer: 'Attested by prior employer', status: 'Verified' }],
  },
  {
    id: 'pc7', ticket: 'G', name: 'Marco Silva', title: 'Product Designer', location: 'Hoboken, NJ', years: 6, allocationRank: 7,
    summary: 'Product designer with deep B2B experience and strong prototyping. Has used, not led, design systems.',
    signals: {
      systems: s('confirmed', false, 'Says they have used, not led, a system'),
      b2b: s('confirmed', true, 'Logistics dashboards, six years'),
      research: s('confirmed', true, 'Runs usability tests monthly'),
      code: s('confirmed', true, 'Prototypes in React'),
      mentoring: s('inferred', true, 'Onboarded junior designers'),
    },
    arrangement: { value: 'Either', status: 'confirmed' },
    floor: { value: 145, status: 'confirmed' },
    priorities: ['Hands-on product work', 'Fast-moving team', 'Learning systems leadership'],
    questions: ['Would the role support growing into systems ownership?'],
    evidence: [{ label: 'Employment history, 2018–present', issuer: 'Attested by prior employer', status: 'Verified' }],
  },
]

/** Scripted demo replies to taste tests, keyed by candidate then subject. */
const replies: Record<string, Record<string, { answer: string; meets: boolean; floor?: number; arrangement?: PassCandidate['arrangement']['value'] }>> = {
  pc1: { code: { answer: 'I prototype interactions in Framer and can read React well enough to pair.', meets: true } },
  pc2: {
    research: { answer: 'I partner with research but have run about a dozen interviews myself this year.', meets: true },
    floor: { answer: 'My compensation expectations have been confirmed privately.', meets: true, floor: 160 },
    arrangement: { answer: 'Two days in the office works for me.', meets: true, arrangement: 'Hybrid' },
  },
  pc3: { systems: { answer: 'Yes — I led our system from the first audit through v2.', meets: true } },
  pc4: {
    systems: { answer: 'I contributed components but did not lead the system.', meets: false },
    b2b: { answer: 'One year on internal admin tools; the rest was consumer.', meets: false },
    arrangement: { answer: 'I would need to stay remote.', meets: false, arrangement: 'Remote only' },
  },
  pc5: { code: { answer: 'Not really — I hand off to prototypers.', meets: false } },
  pc6: {
    b2b: { answer: 'Yes, the CRM was sold to mid-market sales teams.', meets: true },
    code: { answer: 'Some — I build small prototypes in SwiftUI.', meets: true },
    floor: { answer: 'My compensation expectations have been confirmed privately.', meets: true, floor: 155 },
  },
  pc7: {},
}

const initialPass: PassState = { order: initialOrder, candidates, tasteTests: [], pinned: [], introductions: {}, log: [] }

/* ---------------- Evaluation ---------------- */
export type Verdict = 'ready' | 'check' | 'held'
export interface Line { id: string; label: string; weight: RecipeWeight; signal: Signal; state: 'met' | 'missed' | 'open' }
export interface Uncertainty { subject: string; label: string; detail: string }
export interface Evaluation {
  candidate: PassCandidate
  verdict: Verdict
  lines: Line[]
  conflicts: string[]
  uncertainties: Uncertainty[]
  met: { must: number; mustTotal: number; nice: number; niceTotal: number }
  terms: { arrangement: 'fits' | 'conflict' | 'open'; floor: 'fits' | 'conflict' | 'open' }
}

export function evaluate(order: PassOrder, c: PassCandidate): Evaluation {
  const lines: Line[] = order.recipe
    .filter((r) => r.weight !== 'off')
    .map((r) => {
      const signal = c.signals[r.id] ?? s('unknown', false, 'Not known')
      return { id: r.id, label: r.label, weight: r.weight, signal, state: signal.status === 'unknown' ? 'open' : signal.meets ? 'met' : 'missed' }
    })
  const conflicts: string[] = []
  const uncertainties: Uncertainty[] = []
  for (const l of lines) {
    if (l.state === 'open') uncertainties.push({ subject: l.id, label: l.label, detail: l.signal.note })
    else if (l.state === 'missed' && l.weight === 'must') {
      if (l.signal.status === 'confirmed') conflicts.push(`${l.label}: ${l.signal.note.toLowerCase()}`)
      else uncertainties.push({ subject: l.id, label: l.label, detail: `Inferred no — ${l.signal.note.toLowerCase()}` })
    }
  }
  let arrangement: Evaluation['terms']['arrangement'] = 'fits'
  if (order.arrangement.startsWith('Hybrid') && c.arrangement.value === 'Remote only') {
    if (c.arrangement.status === 'confirmed') { arrangement = 'conflict'; conflicts.push('Needs remote; this order is hybrid') }
    else { arrangement = 'open'; uncertainties.push({ subject: 'arrangement', label: 'Work arrangement', detail: 'Profile suggests remote-only' }) }
  } else if (c.arrangement.status === 'unknown') {
    arrangement = 'open'
    uncertainties.push({ subject: 'arrangement', label: 'Work arrangement', detail: 'Not stated' })
  }
  let floor: Evaluation['terms']['floor'] = 'fits'
  if (c.floor.value === null || c.floor.status === 'unknown') {
    floor = 'open'
    uncertainties.push({ subject: 'floor', label: 'Compensation alignment', detail: 'Compatibility with your budget is not confirmed' })
  } else if (c.floor.value > order.ceiling) {
    if (c.floor.status === 'confirmed') { floor = 'conflict'; conflicts.push('Compensation expectations do not align with this role’s budget. The candidate’s exact minimum stays private.') }
    else { floor = 'open'; uncertainties.push({ subject: 'floor', label: 'Compensation alignment', detail: 'Budget compatibility needs confirmation' }) }
  }
  const must = lines.filter((l) => l.weight === 'must')
  const nice = lines.filter((l) => l.weight === 'nice')
  return {
    candidate: c,
    verdict: conflicts.length ? 'held' : uncertainties.length ? 'check' : 'ready',
    lines,
    conflicts,
    uncertainties,
    met: { must: must.filter((l) => l.state === 'met').length, mustTotal: must.length, nice: nice.filter((l) => l.state === 'met').length, niceTotal: nice.length },
    terms: { arrangement, floor },
  }
}

export function arrange(state: PassState) {
  const all = state.candidates.map((c) => evaluate(state.order, c)).sort((a, b) => a.candidate.allocationRank - b.candidate.allocationRank)
  const qualified = all.filter((e) => e.verdict !== 'held' && state.introductions[e.candidate.id] !== 'Passed')
  const suggested = qualified.slice(0, SERVICE_LIMIT)
  const pinned = qualified.filter((e) => state.pinned.includes(e.candidate.id) && !suggested.includes(e))
  const onPass = [...suggested, ...pinned]
  return {
    all,
    onPass,
    suggestedIds: new Set(suggested.map((e) => e.candidate.id)),
    walkIn: qualified.filter((e) => !onPass.includes(e)),
    held: all.filter((e) => e.verdict === 'held'),
    passed: all.filter((e) => e.verdict !== 'held' && state.introductions[e.candidate.id] === 'Passed'),
  }
}

/** Employer-scoped market repair: single changes to this order that would qualify more people. */
export interface Repair { id: string; title: string; detail: string; gain: number; names: string[]; next: PassOrder }
export function repairs(state: PassState): Repair[] {
  const qualifiedIds = (order: PassOrder) => new Set(state.candidates.filter((c) => evaluate(order, c).verdict !== 'held').map((c) => c.id))
  const base = qualifiedIds(state.order)
  const options: Omit<Repair, 'gain' | 'names'>[] = []
  for (const r of state.order.recipe.filter((r) => r.weight === 'must')) {
    options.push({ id: `soften-${r.id}`, title: `Make “${r.label}” a nice-to-have`, detail: 'Keeps it in the recipe without excluding anyone.', next: { ...state.order, recipe: state.order.recipe.map((x) => (x.id === r.id ? { ...x, weight: 'nice' } : x)) } })
  }
  if (state.order.arrangement.startsWith('Hybrid')) options.push({ id: 'remote', title: 'Open the order to remote (US)', detail: 'Hybrid candidates stay eligible.', next: { ...state.order, arrangement: 'Remote (US)' } })
  options.push({ id: 'ceiling', title: `Raise the ceiling to $${state.order.ceiling + 15}k`, detail: 'Only affects people whose stated floor is above the current ceiling.', next: { ...state.order, ceiling: state.order.ceiling + 15 } })
  return options
    .map((o) => {
      const after = qualifiedIds(o.next)
      const names = state.candidates.filter((c) => after.has(c.id) && !base.has(c.id)).map((c) => c.name)
      return { ...o, gain: names.length, names }
    })
    .filter((o) => o.gain > 0)
}

export function tasteTestsLeft(state: PassState) {
  return state.order.verificationBudget - state.tasteTests.length
}

/* ---------------- Store ---------------- */
let pass: PassState = structuredClone(initialPass)
const clock = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

function commit(fn: (draft: PassState) => PassState) {
  pass = fn(structuredClone(pass))
  void globalMutate(KEY, structuredClone(pass), { revalidate: false })
}
function logged(draft: PassState, text: string): PassState {
  return { ...draft, log: [{ id: crypto.randomUUID(), text, time: clock() }, ...draft.log] }
}

export const passActions = {
  setWeight(id: string, weight: RecipeWeight) {
    commit((d) => {
      const item = d.order.recipe.find((r) => r.id === id)
      const label = weight === 'must' ? 'must-have' : weight === 'nice' ? 'nice-to-have' : 'off the recipe'
      return logged({ ...d, order: { ...d.order, recipe: d.order.recipe.map((r) => (r.id === id ? { ...r, weight } : r)) } }, `Recipe: “${item?.label}” set to ${label}`)
    })
  },
  setArrangement(arrangement: Arrangement) {
    commit((d) => logged({ ...d, order: { ...d.order, arrangement } }, `Order arrangement set to ${arrangement}`))
  },
  setCeiling(ceiling: number) {
    commit((d) => logged({ ...d, order: { ...d.order, ceiling } }, `Compensation ceiling set to $${ceiling}k`))
  },
  applyOrder(order: PassOrder, note: string) {
    commit((d) => logged({ ...d, order }, `Applied kitchen note: ${note}`))
  },
  pin(id: string, name: string) {
    commit((d) => logged({ ...d, pinned: [...new Set([...d.pinned, id])] }, `${name} brought to the pass by you`))
  },
  unpin(id: string) {
    commit((d) => ({ ...d, pinned: d.pinned.filter((p) => p !== id) }))
  },
  decide(id: string, name: string, decision: 'Requested' | 'Passed') {
    commit((d) => logged({ ...d, introductions: { ...d.introductions, [id]: decision } }, decision === 'Requested' ? `Introduction requested with ${name}` : `Passed on ${name} for this order`))
  },
  undoDecision(id: string) {
    commit((d) => {
      const next = { ...d.introductions }
      delete next[id]
      return { ...d, introductions: next }
    })
  },
  sendTasteTest(candidateId: string, subject: string, topic: string, question: string) {
    if (tasteTestsLeft(pass) <= 0) return false
    const id = crypto.randomUUID()
    const name = pass.candidates.find((c) => c.id === candidateId)?.name ?? 'Candidate'
    commit((d) => logged({ ...d, tasteTests: [{ id, candidateId, subject, topic, question, status: 'Awaiting reply', sent: clock() }, ...d.tasteTests] }, `Taste test sent to ${name}: ${topic}`))
    const reply = replies[candidateId]?.[subject] ?? { answer: 'I would prefer to discuss this in a first conversation.', meets: false }
    const known = Boolean(replies[candidateId]?.[subject])
    window.setTimeout(() => {
      commit((d) => {
        const candidates = d.candidates.map((c) => {
          if (c.id !== candidateId || !known) return c
          if (subject === 'floor') return { ...c, floor: { value: reply.floor ?? c.floor.value, status: 'confirmed' as const } }
          if (subject === 'arrangement') return { ...c, arrangement: { value: reply.arrangement ?? c.arrangement.value, status: 'confirmed' as const } }
          return { ...c, signals: { ...c.signals, [subject]: { ...c.signals[subject], status: 'confirmed' as const, meets: reply.meets, note: reply.answer } } }
        })
        return logged(
          { ...d, candidates, tasteTests: d.tasteTests.map((t) => (t.id === id ? { ...t, status: 'Answered' as const, answer: reply.answer } : t)) },
          `${name} answered: ${topic}`,
        )
      })
    }, 2600)
    return true
  },
  reset() {
    commit(() => structuredClone(initialPass))
  },
}

export function usePass() {
  const { data = initialPass } = useSWR<PassState>(KEY, () => structuredClone(pass), { fallbackData: initialPass, revalidateOnFocus: false, revalidateOnMount: false })
  return data
}

/** Detached copy for self-contained demos (e.g. the homepage) that must not touch the workspace store. */
export function freshPassState(): PassState {
  return structuredClone(initialPass)
}
