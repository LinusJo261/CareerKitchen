'use client'
import { useState } from 'react'
import { Check, Send, Undo2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
import { ProvenanceGlyph, ProvenanceLegend, provenanceLabel, stateTone, stateWord } from './provenance'
import { compensationAlignment, VerdictStamp } from './candidate-ticket'
import { evaluate, passActions, tasteTestsLeft, type Uncertainty } from '@/lib/demo/pass'
import { cn } from '@/lib/utils'
import type { PassState } from '@/lib/contracts'

const draftQuestion = (u: Uncertainty, ceiling: number) =>
  u.subject === 'floor'
    ? `Would the advertised base salary budget, up to $${ceiling}k, meet your expectations? Your exact minimum stays private.`
    : u.subject === 'arrangement'
      ? 'This role is hybrid with two office days in NYC. Would that work for you?'
      : `Could you tell us a little about your experience with this: “${u.label.toLowerCase()}”?`

export function Inspector({ state, candidateId, onClose }: { state: PassState; candidateId: string | null; onClose: () => void }) {
  const candidate = state.candidates.find((c) => c.id === candidateId)
  return (
    <Sheet open={Boolean(candidate)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto p-0 sm:max-w-3xl">
        {candidate && <InspectorBody key={candidate.id} state={state} candidateId={candidate.id} onClose={onClose} />}
      </SheetContent>
    </Sheet>
  )
}

function InspectorBody({ state, candidateId, onClose }: { state: PassState; candidateId: string; onClose: () => void }) {
  const c = state.candidates.find((x) => x.id === candidateId)!
  const ev = evaluate(state.order, c)
  const tests = state.tasteTests.filter((t) => t.candidateId === c.id)
  const left = tasteTestsLeft(state)
  const askable = ev.uncertainties.filter((u) => !tests.some((t) => t.subject === u.subject))
  const [subject, setSubject] = useState(askable[0]?.subject ?? '')
  const chosen = askable.find((u) => u.subject === subject) ?? askable[0]
  const [question, setQuestion] = useState(chosen ? draftQuestion(chosen, state.order.ceiling) : '')
  const decision = state.introductions[c.id]

  function choose(u: Uncertainty) {
    setSubject(u.subject)
    setQuestion(draftQuestion(u, state.order.ceiling))
  }
  function send() {
    if (!chosen || !question.trim()) return
    if (passActions.sendTasteTest(c.id, chosen.subject, chosen.label, question.trim())) {
      toast.success(`Demo taste test for ${c.name}`, { description: 'A scripted reply arrives in a few seconds. No one was contacted.' })
      const next = askable.find((u) => u.subject !== chosen.subject)
      if (next) choose(next)
      else setSubject('')
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b bg-primary px-6 pt-8 pb-6 text-primary-foreground md:px-10">
        <p className="font-mono text-[11px] tracking-[0.14em] uppercase opacity-75">
          Demo ticket {state.order.ticket}-{c.ticket} · Role alignment for {state.order.title}
        </p>
        <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
          <div>
            <SheetTitle className="font-serif text-4xl font-normal text-primary-foreground">{c.name}</SheetTitle>
            <SheetDescription className="text-primary-foreground/75">{c.title} · {c.years} years · {c.location}</SheetDescription>
          </div>
          <span className="rounded-[2px] bg-card px-1 py-0.5"><VerdictStamp verdict={ev.verdict} /></span>
        </div>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-primary-foreground/85">{c.summary}</p>
      </header>

      <div className="flex flex-col gap-10 px-6 py-8 md:px-10">
        <ProvenanceLegend />

        <section aria-labelledby="fit-sides" className="grid gap-px overflow-hidden rounded-sm border bg-border md:grid-cols-2">
          <h3 id="fit-sides" className="sr-only">Both sides of the fit</h3>
          <div className="bg-card p-5">
            <p className="eyebrow">Your recipe</p>
            <ul className="mt-3 flex flex-col gap-3">
              {ev.lines.map((l) => (
                <li key={l.id} className="flex gap-3 text-sm">
                  <span className={cn('mt-1', stateTone[l.state])}><ProvenanceGlyph status={l.signal.status} /></span>
                  <span className="flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className="font-medium">{l.label}</span>
                      <span className="leader" aria-hidden="true" />
                      <span className={cn('font-mono text-xs', stateTone[l.state])}>{stateWord[l.state]}</span>
                    </span>
                    <span className="block text-muted-foreground">
                      {provenanceLabel[l.signal.status]} · {l.signal.note}
                      {l.weight === 'nice' && ' · nice-to-have'}
                    </span>
                  </span>
                </li>
              ))}
              <li className="flex gap-3 text-sm">
                <span className="mt-1 text-primary"><ProvenanceGlyph status={c.arrangement.status} /></span>
                <span className="flex-1"><span className="font-medium">Arrangement</span> — you offer {state.order.arrangement}; they want {c.arrangement.value.toLowerCase()}.</span>
              </li>
              <li className="flex gap-3 text-sm">
                <span className="mt-1 text-primary"><ProvenanceGlyph status={c.floor.status} /></span>
                <span className="flex-1"><span className="font-medium">Compensation</span> — your ceiling ${state.order.ceiling}k; {compensationAlignment[ev.terms.floor].toLowerCase()}. The candidate’s exact minimum stays private.</span>
              </li>
            </ul>
          </div>
          <div className="bg-card p-5">
            <p className="eyebrow">What {c.name.split(' ')[0]} is looking for</p>
            <ol className="mt-3 flex flex-col gap-3">
              {c.priorities.map((p, i) => (
                <li key={p} className="flex gap-3 text-sm">
                  <span className="font-serif text-lg leading-none text-paprika-ink italic">{i + 1}</span>
                  <span>{p}</span>
                </li>
              ))}
            </ol>
            <p className="eyebrow mt-6">Their questions for you</p>
            <ul className="mt-3 flex flex-col gap-2">
              {c.questions.map((q) => <li key={q} className="border-l-2 border-butter pl-3 text-sm italic">{q}</li>)}
            </ul>
          </div>
        </section>

        {ev.conflicts.length > 0 && (
          <section aria-labelledby="conflicts" className="rounded-sm border border-dashed border-paprika-ink p-5">
            <h3 id="conflicts" className="font-serif text-xl">Why this ticket is held</h3>
            <ul className="mt-2 flex flex-col gap-1 text-sm">{ev.conflicts.map((x) => <li key={x}>{x}</li>)}</ul>
            <p className="mt-2 text-xs text-muted-foreground">Confirmed conflicts only. Changing the recipe may release this ticket.</p>
          </section>
        )}

        <section aria-labelledby="taste" className="ticket-shadow">
          <div className="ticket bg-accent px-6 pt-8 pb-6 text-accent-foreground">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 id="taste" className="font-serif text-2xl">Taste test</h3>
              <span className="font-mono text-[11px] tracking-[0.12em] uppercase">{left} of {state.order.verificationBudget} left on this order</span>
            </div>
            <p className="mt-1 text-sm opacity-80">Explore one open question for {c.name.split(' ')[0]}. Replies are scripted examples and do not verify a real person.</p>

            {askable.length > 0 && left > 0 ? (
              <div className="mt-5 flex flex-col gap-4">
                <div role="radiogroup" aria-label="Open question to verify" className="flex flex-wrap gap-2">
                  {askable.map((u) => (
                    <button
                      key={u.subject}
                      type="button"
                      role="radio"
                      aria-checked={chosen?.subject === u.subject}
                      onClick={() => choose(u)}
                      className={cn(
                        'rounded-sm border border-foreground/25 px-3 py-2 text-left text-sm transition-colors hover:border-foreground',
                        chosen?.subject === u.subject && 'border-foreground bg-card',
                      )}
                    >
                      <span className="block font-medium">{u.label}</span>
                      <span className="block text-xs opacity-75">{u.detail}</span>
                    </button>
                  ))}
                </div>
                <Field>
                  <FieldLabel htmlFor="taste-question">Your question</FieldLabel>
                  <Textarea id="taste-question" value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} className="bg-card" />
                  <FieldDescription className="text-accent-foreground/75">Keep it to one question. Candidates can decline; this demo uses scripted replies.</FieldDescription>
                </Field>
                <Button className="self-start" onClick={send} disabled={!question.trim()}>
                  <Send data-icon="inline-start" />Try demo taste test
                </Button>
              </div>
            ) : (
              <p className="mt-4 text-sm">
                {left <= 0 ? 'This order has used its verification budget.' : ev.uncertainties.length ? 'Every open question already has a taste test.' : 'Nothing is left to verify on this ticket.'}
              </p>
            )}

            {tests.length > 0 && (
              <ul className="mt-6 flex flex-col gap-3 border-t border-foreground/15 pt-4" aria-live="polite">
                {tests.map((t) => (
                  <li key={t.id} className="text-sm">
                    <p className="flex items-center gap-2 font-mono text-[11px] tracking-[0.1em] uppercase">
                      {t.status === 'Answered' ? <Check className="size-3.5" aria-hidden="true" /> : <Spinner className="size-3.5" />}
                      {t.topic} · {t.status} · sent {t.sent}
                    </p>
                    <p className="mt-1 opacity-75">{t.question}</p>
                    {t.answer && <p className="mt-1 border-l-2 border-primary pl-3 font-serif text-base italic">“{t.answer}”</p>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section aria-labelledby="evidence">
          <h3 id="evidence" className="font-serif text-2xl">Evidence</h3>
          <ul className="mt-3 flex flex-col">
            {c.evidence.map((e) => (
              <li key={e.label} className="flex items-baseline gap-3 border-b py-3 text-sm">
                <span className="font-medium">{e.label}</span>
                <span className="leader" aria-hidden="true" />
                <span className="text-muted-foreground">{e.issuer}</span>
                <span className={cn('font-mono text-[11px] tracking-[0.1em] uppercase', e.status === 'Verified' ? 'text-primary' : 'text-muted-foreground')}>{e.status}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <footer className="sticky bottom-0 mt-auto flex flex-wrap items-center justify-between gap-3 border-t bg-card px-6 py-4 md:px-10">
        <p className="max-w-md text-xs text-muted-foreground">
          Allocation suggested this ticket at #{c.allocationRank}. Whether to make an introduction is your decision.
        </p>
        {decision ? (
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium">{decision === 'Requested' ? 'Introduction requested' : 'Passed for this order'}</span>
            <Button variant="ghost" size="sm" onClick={() => passActions.undoDecision(c.id)}><Undo2 data-icon="inline-start" />Undo</Button>
          </div>
        ) : (
          <div className="flex gap-2">
            <Button variant="outline" disabled={ev.verdict === 'held'} onClick={() => { passActions.decide(c.id, c.name, 'Passed'); toast(`Passed on ${c.name}`); onClose() }}>
              Pass for this order
            </Button>
            <Button disabled={ev.verdict === 'held'} onClick={() => { passActions.decide(c.id, c.name, 'Requested'); toast.success(`Demo introduction requested with ${c.name}`, { description: 'No one was contacted. An introduction requires the candidate’s agreement too.' }) }}>
              Request introduction
            </Button>
          </div>
        )}
      </footer>
    </div>
  )
}
