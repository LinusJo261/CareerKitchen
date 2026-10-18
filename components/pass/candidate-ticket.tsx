'use client'
import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Button } from '@/components/ui/button'
import { ProvenanceGlyph, provenanceLabel, stateTone, stateWord } from './provenance'
import { cn } from '@/lib/utils'
import type { Evaluation } from '@/lib/demo/pass'
import type { PassOrder } from '@/lib/contracts'

function signature(ev: Evaluation) {
  return `${ev.verdict}|${ev.lines.map((l) => l.id + l.state + l.weight).join(',')}|${ev.terms.arrangement}|${ev.terms.floor}`
}

export function useChanged(sig: string) {
  const prev = useRef(sig)
  const [changed, setChanged] = useState(false)
  useEffect(() => {
    if (prev.current === sig) return
    prev.current = sig
    setChanged(true)
    const t = window.setTimeout(() => setChanged(false), 1800)
    return () => window.clearTimeout(t)
  }, [sig])
  return changed
}

export function VerdictStamp({ verdict }: { verdict: Evaluation['verdict'] }) {
  if (verdict === 'ready') return <span className="stamp border-primary text-primary">Ready</span>
  if (verdict === 'check') return <span className="stamp border-paprika-ink text-paprika-ink">To verify</span>
  return <span className="stamp border-muted-foreground text-muted-foreground">Held</span>
}

export const compensationAlignment: Record<Evaluation['terms']['floor'], string> = {
  fits: 'Aligns with your budget',
  conflict: 'Outside your budget',
  open: 'Alignment to confirm',
}

interface Props {
  ev: Evaluation
  order: PassOrder
  index: number
  suggested: boolean
  decision?: 'Requested' | 'Passed'
  pendingTests: number
  onInspect: () => void
  onReturn?: () => void
}

export function CandidateTicket({ ev, order, index, suggested, decision, pendingTests, onInspect, onReturn }: Props) {
  const reduce = useReducedMotion()
  const changed = useChanged(signature(ev))
  const c = ev.candidate
  const tilt = reduce ? 0 : index % 2 ? 0.6 : -0.5

  return (
    <motion.li
      layout={!reduce}
      initial={reduce ? false : { opacity: 0, y: -32 }}
      animate={{ opacity: 1, y: 0, rotate: tilt }}
      exit={reduce ? { opacity: 0 } : { opacity: 0, y: 48, rotate: tilt * 3, transition: { duration: 0.28 } }}
      transition={{ type: 'spring', stiffness: 240, damping: 26 }}
      className="relative w-[272px] shrink-0 pt-4"
      style={{ transformOrigin: '50% 0' }}
    >
      <span aria-hidden="true" className="absolute top-0 left-1/2 z-10 h-6 w-12 -translate-x-1/2 rounded-b-[3px] bg-steel" />
      <div className="ticket-shadow">
        <article
          aria-labelledby={`ticket-${c.id}`}
          className={cn('ticket flex flex-col px-5 pt-7 pb-5 transition-colors duration-500', changed && 'bg-accent')}
        >
          <div className="flex items-start justify-between gap-2">
            <span className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
              {order.ticket}-{c.ticket}
            </span>
            <AnimatePresence mode="wait" initial={false}>
              <motion.span key={ev.verdict} initial={reduce ? false : { scale: 1.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ opacity: 0 }}>
                <VerdictStamp verdict={ev.verdict} />
              </motion.span>
            </AnimatePresence>
          </div>
          <h3 id={`ticket-${c.id}`} className="mt-2 font-serif text-[26px] leading-tight">{c.name}</h3>
          <p className="text-sm text-muted-foreground">{c.title} · {c.years} yrs</p>
          <p className="text-sm text-muted-foreground">{c.location}</p>
          <p className="mt-2 font-mono text-[10px] tracking-[0.12em] uppercase">
            {suggested ? <>Suggested · allocation #{c.allocationRank}</> : <span className="text-paprika-ink">Brought to the pass by you</span>}
          </p>

          <div className="rule-dashed my-4" />
          <ul aria-label="Recipe alignment" className="flex flex-col gap-2">
            {ev.lines.map((l) => (
              <li key={l.id} className="flex items-center gap-2.5 text-sm">
                <span className={stateTone[l.state]}><ProvenanceGlyph status={l.signal.status} /></span>
                <span className={cn('min-w-0 flex-1 truncate', l.weight === 'nice' && 'text-muted-foreground')}>
                  {l.label}
                  <span className="sr-only">, {l.weight === 'must' ? 'must-have' : 'nice-to-have'}, {provenanceLabel[l.signal.status]}</span>
                </span>
                <span className={cn('font-mono text-xs', stateTone[l.state])}>{stateWord[l.state]}</span>
              </li>
            ))}
          </ul>

          <div className="rule-dashed my-4" />
          <dl className="flex flex-col gap-1.5 text-sm">
            <div className="flex items-center gap-2.5">
              <dt className="sr-only">Arrangement</dt>
              <span className={ev.terms.arrangement === 'open' ? 'text-muted-foreground' : 'text-primary'}><ProvenanceGlyph status={c.arrangement.status} /></span>
              <dd className="flex-1">{c.arrangement.value === 'Either' ? 'Hybrid or remote' : c.arrangement.value}</dd>
            </div>
            <div className="flex items-center gap-2.5">
              <dt className="sr-only">Compensation alignment</dt>
              <span className={ev.terms.floor === 'open' ? 'text-muted-foreground' : ev.terms.floor === 'conflict' ? 'text-paprika-ink' : 'text-primary'}><ProvenanceGlyph status={c.floor.status} /></span>
              <dd className="flex-1">{compensationAlignment[ev.terms.floor]}</dd>
            </div>
          </dl>
          <p className="mt-2 text-xs text-muted-foreground">The candidate’s exact minimum stays private.</p>

          <p className="mt-4 font-mono text-[11px] tracking-[0.08em] uppercase">
            {pendingTests > 0 ? (
              <span className="text-paprika-ink">Taste test out · awaiting reply</span>
            ) : ev.uncertainties.length ? (
              <span className="text-paprika-ink">{ev.uncertainties.length} open {ev.uncertainties.length === 1 ? 'question' : 'questions'}</span>
            ) : (
              <span className="text-primary">Nothing left to verify</span>
            )}
          </p>

          {decision === 'Requested' && <p className="mt-3"><span className="stamp border-primary bg-primary text-primary-foreground">Intro requested</span></p>}

          <div className="mt-4 flex items-center gap-2">
            <Button size="sm" className="flex-1" onClick={onInspect} aria-label={`Inspect fit with ${c.name}`}>Inspect fit</Button>
            {onReturn && <Button size="sm" variant="ghost" onClick={onReturn} aria-label={`Return ${c.name} to the bench`}>Return</Button>}
          </div>
        </article>
      </div>
    </motion.li>
  )
}
