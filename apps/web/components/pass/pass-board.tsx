'use client'
import { useState } from 'react'
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'motion/react'
import { ArrowUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { OrderTicket } from './order-ticket'
import { CandidateTicket } from './candidate-ticket'
import { Inspector } from './inspector'
import { ProvenanceLegend } from './provenance'
import { arrange, passActions, SERVICE_LIMIT, usePass } from '@/lib/demo/pass'

export function PassBoard() {
  const state = usePass()
  const reduce = useReducedMotion()
  const [inspecting, setInspecting] = useState<string | null>(null)
  const { onPass, suggestedIds, walkIn, held, passed } = arrange(state)
  const pending = (id: string) => state.tasteTests.filter((t) => t.candidateId === id && t.status === 'Awaiting reply').length

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="max-w-2xl">
          <p className="eyebrow">Expediting · Order {state.order.ticket}</p>
          <h1 className="display mt-2 text-6xl md:text-7xl">The Pass</h1>
          <p className="mt-3 text-pretty text-muted-foreground">
            Global allocation suggests up to {SERVICE_LIMIT} tickets for this round. Every qualified candidate stays within reach — bring anyone up from the bench.
          </p>
        </div>
        <ProvenanceLegend />
      </header>

      <div className="grid items-start gap-8 lg:grid-cols-[340px_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-24"><OrderTicket state={state} /></div>

        <LayoutGroup>
          <div className="flex min-w-0 flex-col gap-10">
            <section aria-labelledby="on-pass">
              <div className="flex items-baseline justify-between gap-3">
                <h2 id="on-pass" className="text-3xl">On the pass</h2>
                <p className="font-mono text-[11px] tracking-[0.12em] text-muted-foreground uppercase" aria-live="polite">
                  {onPass.length} {onPass.length === 1 ? 'ticket' : 'tickets'} · {walkIn.length} on the bench · {held.length} held
                </p>
              </div>
              <div className="rail mt-4" aria-hidden="true" />
              {onPass.length === 0 ? (
                <div className="mt-6 rounded-sm border border-dashed p-10 text-center">
                  <p className="font-serif text-2xl">The rail is empty</p>
                  <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">Nobody qualifies under this recipe. Try a kitchen note on the order ticket to loosen one requirement.</p>
                </div>
              ) : (
                <ul className="-mt-1 flex gap-5 overflow-x-auto px-1 pb-6">
                  <AnimatePresence mode="popLayout" initial={false}>
                    {onPass.map((ev, i) => (
                      <CandidateTicket
                        key={ev.candidate.id}
                        ev={ev}
                        order={state.order}
                        index={i}
                        suggested={suggestedIds.has(ev.candidate.id)}
                        decision={state.introductions[ev.candidate.id]}
                        pendingTests={pending(ev.candidate.id)}
                        onInspect={() => setInspecting(ev.candidate.id)}
                        onReturn={suggestedIds.has(ev.candidate.id) ? undefined : () => passActions.unpin(ev.candidate.id)}
                      />
                    ))}
                  </AnimatePresence>
                </ul>
              )}
            </section>

            <div className="grid gap-8 xl:grid-cols-2">
              <section aria-labelledby="bench" className="flex flex-col gap-3">
                <div>
                  <h2 id="bench" className="text-2xl">The bench</h2>
                  <p className="text-sm text-muted-foreground">Qualified, but not suggested for this round. Your call.</p>
                </div>
                {walkIn.length === 0 ? (
                  <p className="rounded-sm border border-dashed p-4 text-sm text-muted-foreground">No one else qualifies right now.</p>
                ) : (
                  <ul className="flex flex-col border-t">
                    <AnimatePresence initial={false}>
                      {walkIn.map((ev) => (
                        <motion.li
                          key={ev.candidate.id}
                          layout={!reduce}
                          initial={reduce ? false : { opacity: 0, x: -12 }}
                          animate={{ opacity: 1, x: 0 }}
                          exit={{ opacity: 0 }}
                          className="flex items-center gap-3 border-b py-3"
                        >
                          <span className="font-mono text-[11px] text-muted-foreground">{state.order.ticket}-{ev.candidate.ticket}</span>
                          <button type="button" className="min-w-0 flex-1 truncate text-left font-serif text-lg hover:underline" onClick={() => setInspecting(ev.candidate.id)}>
                            {ev.candidate.name}
                          </button>
                          <span className="hidden font-mono text-[11px] text-muted-foreground sm:inline">
                            {ev.met.must}/{ev.met.mustTotal} must · {ev.uncertainties.length} open
                          </span>
                          <Button size="sm" variant="outline" onClick={() => passActions.pin(ev.candidate.id, ev.candidate.name)}>
                            <ArrowUp data-icon="inline-start" />Bring up
                          </Button>
                        </motion.li>
                      ))}
                    </AnimatePresence>
                  </ul>
                )}
              </section>

              <section aria-labelledby="held" className="flex flex-col gap-3">
                <div>
                  <h2 id="held" className="text-2xl">Held tickets</h2>
                  <p className="text-sm text-muted-foreground">A confirmed conflict with this order. Shown so nothing is hidden from you.</p>
                </div>
                {held.length === 0 ? (
                  <p className="rounded-sm border border-dashed p-4 text-sm text-muted-foreground">Nothing is held. Every candidate qualifies.</p>
                ) : (
                  <ul className="flex flex-col border-t">
                    <AnimatePresence initial={false}>
                      {held.map((ev) => (
                        <motion.li key={ev.candidate.id} layout={!reduce} initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="border-b py-3">
                          <button type="button" className="font-serif text-lg text-muted-foreground hover:text-foreground hover:underline" onClick={() => setInspecting(ev.candidate.id)}>
                            {ev.candidate.name}
                          </button>
                          <p className="text-sm text-muted-foreground">{ev.conflicts[0]}</p>
                        </motion.li>
                      ))}
                    </AnimatePresence>
                  </ul>
                )}
                {passed.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    Passed for this order: {passed.map((p, i) => (
                      <span key={p.candidate.id}>
                        {i > 0 && ', '}
                        <button type="button" className="underline" onClick={() => passActions.undoDecision(p.candidate.id)}>{p.candidate.name} (undo)</button>
                      </span>
                    ))}
                  </p>
                )}
              </section>
            </div>

            <section aria-labelledby="log" className="double-rule pt-5">
              <h2 id="log" className="eyebrow">Service log</h2>
              {state.log.length === 0 ? (
                <p className="mt-2 text-sm text-muted-foreground">Changes you make on the pass are logged here.</p>
              ) : (
                <ol className="mt-2 flex flex-col gap-1 font-mono text-xs" aria-live="polite">
                  {state.log.slice(0, 6).map((l) => (
                    <li key={l.id} className="flex gap-4"><span className="text-muted-foreground">{l.time}</span><span>{l.text}</span></li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        </LayoutGroup>
      </div>

      <Inspector state={state} candidateId={inspecting} onClose={() => setInspecting(null)} />
    </div>
  )
}
