'use client'

import { useState } from 'react'
import {
  BriefcaseBusiness,
  Check,
  Clock3,
  FileSearch,
  ShieldCheck,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { EmptyNote, SectionTitle } from '@/components/workspace/kit'
import { useWorkspace } from '@/lib/workspace'
import type { components } from '@/packages/api-client/src/schema'

type Card = components['schemas']['DecisionCardOut']

export function PassBoard() {
  const { data, execute } = useWorkspace()
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const vacancy =
    data.backend.vacancies.find((v) => v.id === selected) ??
    data.backend.vacancies[0]
  const cards = data.backend.employerDecisions.filter(
    (c) => c.vacancy.id === vacancy?.id,
  )
  const capacity = vacancy ? data.backend.capacities[vacancy.id] : undefined
  const shortlist = vacancy ? data.backend.shortlist[vacancy.id] : undefined

  async function answer(card: Card, interested: boolean) {
    setBusy(card.id)
    try {
      await execute(
        'decision.answer',
        {
          id: card.id,
          interested,
          expected_cycle_version: card.cycle_version,
          decision_token: card.decision_token,
        },
        interested
          ? 'Interest shared. The pipeline opens only after mutual interest.'
          : 'Passed on this introduction.',
      )
    } finally {
      setBusy(null)
    }
  }
  async function replan() {
    if (!vacancy) return
    setBusy('research')
    try {
      await execute(
        'research.replan',
        { vacancyId: vacancy.id, expected_version: vacancy.version },
        'Read-only shadow analysis requested. Live introductions are unchanged.',
      )
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="max-w-2xl">
          <p className="eyebrow">Employer introductions</p>
          <h1 className="display mt-2 text-6xl md:text-7xl">The Pass</h1>
          <p className="mt-3 text-pretty text-muted-foreground">
            Review the introductions delivered to this vacancy. Each decision
            respects candidate and vacancy attention ceilings, and the process
            opens only after both sides opt in.
          </p>
        </div>
        {data.backend.vacancies.length > 0 && (
          <select
            className="border-input bg-background min-h-9 max-w-full rounded-md border px-3 py-2 text-sm"
            aria-label="Choose vacancy for introductions"
            value={vacancy?.id ?? ''}
            onChange={(e) => setSelected(e.target.value)}
          >
            {data.backend.vacancies.map((v) => (
              <option key={v.id} value={v.id}>
                {v.title}
              </option>
            ))}
          </select>
        )}
      </header>
      {!vacancy ? (
        <EmptyNote
          icon={BriefcaseBusiness}
          title="Create a vacancy to begin"
          description="Once a verified, active vacancy receives introductions, its decision cards appear here."
        />
      ) : (
        <div className="grid items-start gap-8 lg:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="flex flex-col gap-5 lg:sticky lg:top-24">
            <section className="panel flex flex-col gap-4 p-6">
              <div className="flex justify-between gap-3">
                <p className="eyebrow">Role version {vacancy.version}</p>
                <Badge variant="outline">{vacancy.state.toLowerCase()}</Badge>
              </div>
              <h2 className="font-serif text-3xl">{vacancy.title}</h2>
              <p className="text-sm text-muted-foreground">
                {vacancy.location_region || 'Remote'} ·{' '}
                {vacancy.work_mode.toLowerCase()}
              </p>
              <p className="text-sm">
                {vacancy.currency} {Number(vacancy.pay_min).toLocaleString()} –{' '}
                {Number(vacancy.pay_max).toLocaleString()} /{' '}
                {vacancy.compensation_period.toLowerCase()}
              </p>
              <div className="border-t pt-4">
                <p className="text-sm font-medium">
                  {capacity?.used ?? cards.length} /{' '}
                  {capacity?.maximum ?? vacancy.cap} active decisions
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  This ceiling limits concurrent decision cards. Responding
                  frees capacity for a later introduction.
                </p>
              </div>
              <dl className="flex flex-col gap-3 text-sm">
                {vacancy.requirements.map((r) => (
                  <div key={r.id}>
                    <dt className="text-xs text-muted-foreground">
                      {r.kind.toLowerCase()}
                    </dt>
                    <dd>{r.description}</dd>
                  </div>
                ))}
              </dl>
            </section>
            <section className="panel flex flex-col gap-3 p-5">
              <SectionTitle title="Matching research" />
              <Badge variant="outline" className="self-start">
                {shortlist?.mode ?? 'Awaiting status'}
              </Badge>
              <p className="text-sm text-muted-foreground">
                Experimental analysis runs in read-only shadow mode. It cannot
                issue advanced live introductions or certify hiring reliability.
              </p>
              {shortlist && (
                <p className="font-mono text-[11px] text-muted-foreground">
                  {shortlist.certification_state}
                </p>
              )}
              {shortlist?.mode === 'SHADOW' && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy === 'research'}
                  onClick={replan}
                >
                  {busy === 'research'
                    ? 'Requesting…'
                    : 'Request shadow analysis'}
                </Button>
              )}
            </section>
          </aside>
          <div className="flex min-w-0 flex-col gap-6">
            <section aria-labelledby="on-pass">
              <div className="flex items-baseline justify-between gap-3">
                <h2 id="on-pass" className="text-3xl">
                  On the pass
                </h2>
                <p
                  className="font-mono text-[11px] text-muted-foreground"
                  aria-live="polite"
                >
                  {cards.length} active introduction(s)
                </p>
              </div>
              <div className="rail mt-4" aria-hidden="true" />
              {!cards.length ? (
                <div className="mt-6 rounded-sm border border-dashed p-10 text-center">
                  <p className="font-serif text-2xl">The rail is empty</p>
                  <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
                    No active employer decision cards are available for this
                    vacancy. Introductions appear when the backend delivers them
                    within both attention ceilings.
                  </p>
                </div>
              ) : (
                <ul className="mt-6 grid items-start gap-5 xl:grid-cols-2">
                  {cards.map((card) => (
                    <DecisionTicket
                      key={`${card.id}-${card.cycle_version}`}
                      card={card}
                      busy={busy === card.id}
                      answer={answer}
                    />
                  ))}
                </ul>
              )}
            </section>
            <Alert>
              <ShieldCheck />
              <AlertTitle>Candidate disclosure stays scoped</AlertTitle>
              <AlertDescription>
                These cards show only information disclosed by the backend for
                this introduction. Private compensation floors and undisclosed
                evidence are unavailable.
              </AlertDescription>
            </Alert>
          </div>
        </div>
      )}
    </div>
  )
}

function DecisionTicket({
  card,
  busy,
  answer,
}: {
  card: Card
  busy: boolean
  answer: (card: Card, interested: boolean) => Promise<void>
}) {
  const c = card.candidate
  const expired = new Date(card.expires_at).getTime() <= Date.now()
  const actionable =
    card.status === 'ACTIVE' && !expired && Boolean(card.decision_token)
  return (
    <li className="ticket flex flex-col gap-5 border bg-card p-6 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="font-mono text-[11px] tracking-wider text-muted-foreground">
          INTRODUCTION {card.id.slice(0, 8).toUpperCase()}
        </p>
        <Badge variant="outline">
          {card.other_side_interested
            ? 'Candidate interested'
            : 'Your decision'}
        </Badge>
      </div>
      <div>
        <h3 className="font-serif text-2xl">
          {c?.headline ?? 'Candidate introduction'}
        </h3>
        {c && <p className="mt-1 text-sm text-muted-foreground">{c.region}</p>}
      </div>
      {c?.summary && (
        <p className="whitespace-pre-wrap text-sm text-muted-foreground">
          {c.summary}
        </p>
      )}
      {c && (
        <>
          <div className="flex flex-wrap gap-2">
            {c.skills.map((skill) => (
              <Badge key={skill} variant="outline">
                {skill}
              </Badge>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Skills and profile statements are self-reported unless independently
            verified evidence is explicitly disclosed.
          </p>
          <p className="text-sm">
            {c.compensation_aligned
              ? 'Compensation range aligned'
              : 'Compensation alignment needs review'}
          </p>
        </>
      )}
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <Clock3 className="size-3.5" />
        {expired
          ? 'Decision expired'
          : `Respond by ${new Date(card.expires_at).toLocaleString()}`}
      </p>
      {c && (
        <Dialog>
          <DialogTrigger asChild>
            <Button size="sm" variant="outline">
              <FileSearch data-icon="inline-start" />
              Review disclosed profile
            </Button>
          </DialogTrigger>
          <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{c.headline}</DialogTitle>
              <DialogDescription>
                {c.region} · Profile statements are self-reported.
              </DialogDescription>
            </DialogHeader>
            <p className="whitespace-pre-wrap text-sm">{c.summary}</p>
            {(c.experiences?.length ?? 0) > 0 && (
              <section>
                <SectionTitle title="Disclosed experience" />
                <ul className="flex flex-col gap-3">
                  {(c.experiences ?? []).map((experience, i) => (
                    <li key={i} className="rounded-md bg-muted p-3 text-sm">
                      <p className="font-medium">
                        {String(experience.title ?? 'Experience')}
                      </p>
                      {Boolean(experience.organization_label) && (
                        <p>{String(experience.organization_label)}</p>
                      )}
                      {Boolean(experience.details) && (
                        <p className="mt-1 whitespace-pre-wrap text-muted-foreground">
                          {String(experience.details)}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {(c.education?.length ?? 0) > 0 && (
              <section>
                <SectionTitle title="Disclosed education" />
                <ul className="flex flex-col gap-3">
                  {(c.education ?? []).map((education, i) => (
                    <li key={i} className="rounded-md bg-muted p-3 text-sm">
                      <p className="font-medium">
                        {String(education.qualification ?? 'Education')}
                      </p>
                      {Boolean(education.institution) && (
                        <p>{String(education.institution)}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </DialogContent>
        </Dialog>
      )}
      <div className="mt-auto flex gap-2 border-t pt-4">
        <Button
          className="flex-1"
          size="sm"
          disabled={busy || !actionable}
          onClick={() => answer(card, true)}
        >
          <Check data-icon="inline-start" />
          {busy ? 'Saving…' : 'Share interest'}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={busy || !actionable}
          onClick={() => answer(card, false)}
        >
          <X data-icon="inline-start" />
          Pass
        </Button>
      </div>
    </li>
  )
}
