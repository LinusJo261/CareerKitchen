'use client'
import { useState } from 'react'
import {
  ArrowUpRight,
  ArrowRight,
  MapPin,
  Check,
  X,
  BadgeCheck,
  Sparkles,
  Clock3,
  HeartHandshake,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet'
import { CompanyMark } from '@/components/brand'
import { useWorkspace } from '@/lib/workspace'
import type { Opportunity, CandidateProfile, Role } from '@/lib/contracts'
import { Input } from '@/components/ui/input'

export function OpportunityCard({
  opportunity,
  compact = false,
}: {
  opportunity: Opportunity
  compact?: boolean
}) {
  const { data, execute } = useWorkspace()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const decision = data.decisions[opportunity.id]
  async function decide(interested: boolean) {
    if (busy || !opportunity.decisionId || !opportunity.decisionToken) return
    setBusy(true)
    const saved = await execute(
      'decision.answer',
      {
        id: opportunity.decisionId,
        interested,
        expected_cycle_version: opportunity.cycleVersion,
        decision_token: opportunity.decisionToken,
      },
      interested
        ? 'Interest shared. A match requires the employer’s interest too.'
        : 'Opportunity passed. Your preferences remain unchanged.',
    )
    if (saved) setOpen(false)
    setBusy(false)
  }
  const disabled = busy || !opportunity.decisionId || !opportunity.decisionToken
  return (
    <article className="panel flex flex-col overflow-hidden transition-shadow hover:shadow-md hover:shadow-foreground/3">
      <div className="flex flex-col gap-4 p-5 md:p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <CompanyMark name={opportunity.company} />
            <div>
              <span className="flex items-center gap-1.5 text-sm font-medium">
                {opportunity.company}
                {opportunity.verified && (
                  <BadgeCheck
                    className="size-4 text-primary"
                    aria-label="Employer verified"
                  />
                )}
              </span>
              <span className="text-xs text-muted-foreground">
                {opportunity.employmentType}
              </span>
            </div>
          </div>
          {opportunity.employerInterested ? (
            <Badge variant="secondary">
              <Sparkles data-icon="inline-start" />
              Interested in you
            </Badge>
          ) : (
            <span className="text-xs text-muted-foreground">
              New introduction
            </span>
          )}
        </div>
        <div>
          <button onClick={() => setOpen(true)} className="text-left">
            <h3 className="text-xl font-medium tracking-tight hover:text-primary">
              {opportunity.title}
            </h3>
          </button>
          <p className="mt-2 flex items-center gap-1.5 text-sm text-muted-foreground">
            <MapPin className="size-3.5" />
            {opportunity.location}
            <span className="mx-1">·</span>
            {opportunity.arrangement}
          </p>
          <p className="mt-3 text-sm font-medium">{opportunity.salary}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {opportunity.skills.map((skill) => (
            <Badge variant="outline" key={skill}>
              {skill}
            </Badge>
          ))}
        </div>
        {!compact && (
          <div className="rounded-lg bg-secondary p-3 text-sm text-secondary-foreground">
            <span className="mb-1 flex items-center gap-1.5 font-medium">
              <Sparkles className="size-3.5" />
              Introduction context
            </span>
            <p className="text-xs leading-relaxed">{opportunity.reason}</p>
          </div>
        )}
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <Clock3 className="size-3.5" />
            Respond by {opportunity.deadline}
          </span>
          <button
            className="flex items-center gap-1 hover:text-primary"
            onClick={() => setOpen(true)}
          >
            View details <ArrowUpRight className="size-3.5" />
          </button>
        </div>
      </div>
      <div className="mt-auto flex items-center gap-2 border-t bg-muted/30 px-5 py-3">
        {decision ? (
          <p className="text-sm text-primary">
            {decision === 'interested'
              ? 'Interest shared · Awaiting response'
              : 'Passed'}
          </p>
        ) : (
          <>
            <Button
              disabled={disabled}
              variant="outline"
              className="flex-1"
              onClick={() => decide(false)}
            >
              <X data-icon="inline-start" />
              Pass
            </Button>
            <Button
              disabled={disabled}
              className="flex-1"
              onClick={() => decide(true)}
            >
              <Check data-icon="inline-start" />
              Interested
            </Button>
          </>
        )}
      </div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="overflow-y-auto sm:max-w-lg">
          <SheetHeader>
            <CompanyMark name={opportunity.company} />
            <SheetTitle className="mt-4">{opportunity.title}</SheetTitle>
            <SheetDescription>
              {opportunity.company} · {opportunity.location} ·{' '}
              {opportunity.arrangement}
            </SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-6 p-5">
            <p className="text-lg font-medium">{opportunity.salary}</p>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">
              {opportunity.summary}
            </p>
            <section>
              <h3 className="mb-3 font-medium">Role requirements</h3>
              <ul className="flex flex-col gap-3">
                {opportunity.skills.map((skill) => (
                  <li className="flex items-center gap-2 text-sm" key={skill}>
                    <Check className="size-4 text-primary" />
                    {skill}
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-xl bg-secondary p-4">
              <h3 className="mb-2 font-medium text-primary">
                A considered introduction
              </h3>
              <p className="text-sm text-muted-foreground">
                {opportunity.reason}
              </p>
            </section>
            <p className="text-sm text-muted-foreground">
              Respond by {opportunity.deadline}. Sharing interest is not a
              commitment. A match is established only when both sides explicitly
              agree.
            </p>
            {!decision && (
              <div className="flex gap-3">
                <Button
                  disabled={disabled}
                  variant="outline"
                  onClick={() => decide(false)}
                >
                  Pass
                </Button>
                <Button disabled={disabled} onClick={() => decide(true)}>
                  I’m interested
                  <ArrowRight data-icon="inline-end" />
                </Button>
              </div>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </article>
  )
}

export function ReviewPage({ role }: { role: Role }) {
  const { data } = useWorkspace()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('review')
  const employer = role === 'employer'
  const opportunities = data.opportunities.filter(
    (opportunity) =>
      opportunity.status === 'Active' &&
      (filter === 'all' ||
        (filter === 'review'
          ? !data.decisions[opportunity.id]
          : data.decisions[opportunity.id] === 'interested')) &&
      `${opportunity.title} ${opportunity.company} ${opportunity.skills.join(' ')}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  )
  const candidates = data.candidates.filter(
    (candidate) =>
      (filter === 'all' ||
        (filter === 'review'
          ? !data.candidateDecisions[candidate.id]
          : data.candidateDecisions[candidate.id] === 'interested')) &&
      `${candidate.name} ${candidate.skills.join(' ')}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  )
  return (
    <>
      <div className="mb-8">
        <p className="eyebrow mb-3">Thoughtful introductions</p>
        <h1 className="text-3xl font-medium">
          {employer
            ? 'Good people. Shared possibilities.'
            : 'A few possibilities worth exploring.'}
        </h1>
        <p className="mt-3 text-muted-foreground">
          {employer
            ? 'Review authorized candidate summaries and share interest to begin a mutual conversation.'
            : `Your active decision capacity is ${data.profile.capacity}. Take your time with the opportunities in front of you.`}
        </p>
      </div>
      <div className="mb-6 flex flex-wrap justify-between gap-3">
        <div className="flex gap-2">
          {[
            ['review', 'To review'],
            ['interested', 'Interested'],
            ['all', 'All introductions'],
          ].map(([value, label]) => (
            <Button
              key={value}
              variant={filter === value ? 'default' : 'outline'}
              size="sm"
              onClick={() => setFilter(value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <Input
          aria-label="Search introductions"
          placeholder="Search introductions…"
          className="max-w-xs"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {employer
          ? candidates.map((candidate) => (
              <CandidateCard
                key={candidate.decisionId || candidate.id}
                candidate={candidate}
              />
            ))
          : opportunities.map((opportunity) => (
              <OpportunityCard
                key={opportunity.decisionId || opportunity.id}
                opportunity={opportunity}
              />
            ))}
      </div>
      {(employer ? candidates : opportunities).length === 0 && (
        <div className="panel py-20 text-center">
          <HeartHandshake className="mx-auto mb-4 size-8 text-primary" />
          <h2 className="text-xl font-medium">A little room to breathe.</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            No introductions here. Try another filter or review your existing
            conversations.
          </p>
        </div>
      )}
    </>
  )
}

export function CandidateCard({ candidate }: { candidate: CandidateProfile }) {
  const { data, execute } = useWorkspace()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const decision = data.candidateDecisions[candidate.id]
  const card = data.backend.employerDecisions.find(
    (item) => item.id === candidate.decisionId,
  )
  const disabled = busy || !card?.decision_token
  async function decide(interested: boolean) {
    if (busy || !card?.decision_token) return
    setBusy(true)
    const saved = await execute(
      'decision.answer',
      {
        id: card.id,
        interested,
        expected_cycle_version: card.cycle_version,
        decision_token: card.decision_token,
      },
      interested
        ? 'Interest shared. Mutual introductions appear in your pipeline.'
        : 'Candidate passed for this role.',
    )
    if (saved) setOpen(false)
    setBusy(false)
  }
  return (
    <article className="panel flex flex-col gap-5 p-6">
      <div className="flex items-center gap-3">
        <span className="flex size-12 items-center justify-center rounded-full bg-accent text-lg">
          {candidate.name
            .split(' ')
            .map((name) => name[0])
            .join('')}
        </span>
        <div>
          <h3 className="text-lg font-medium">{candidate.name}</h3>
          <p className="text-xs text-muted-foreground">{candidate.location}</p>
        </div>
      </div>
      <div>
        <p className="font-medium">{candidate.title}</p>
        <p className="mt-2 text-sm text-muted-foreground">
          {candidate.summary}
        </p>
        {card && (
          <p className="mt-2 text-xs text-muted-foreground">
            For {card.vacancy.title}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {candidate.skills.map((skill) => (
          <Badge key={skill} variant="outline">
            {skill}
          </Badge>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        {candidate.experience} experience · {candidate.availability}
      </p>
      <Button variant="outline" onClick={() => setOpen(true)}>
        View authorized summary
        <ArrowUpRight data-icon="inline-end" />
      </Button>
      <div className="mt-auto flex gap-2 border-t pt-4">
        {decision ? (
          <p className="text-sm text-primary">
            {decision === 'interested'
              ? 'Interest shared · Awaiting response'
              : 'Passed'}
          </p>
        ) : (
          <>
            <Button
              disabled={disabled}
              className="flex-1"
              variant="outline"
              onClick={() => decide(false)}
            >
              Pass
            </Button>
            <Button
              disabled={disabled}
              className="flex-1"
              onClick={() => decide(true)}
            >
              Interested
            </Button>
          </>
        )}
      </div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>{candidate.name}</SheetTitle>
            <SheetDescription>
              {candidate.title} · Authorized candidate summary
            </SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-6 p-5">
            <p>{candidate.summary}</p>
            <p className="text-sm">
              Experience: {candidate.experience}
              <br />
              Availability: {candidate.availability}
              <br />
              Work arrangement: {candidate.remote}
            </p>
            <div className="flex flex-wrap gap-2">
              {candidate.skills.map((skill) => (
                <Badge key={skill} variant="secondary">
                  {skill}
                </Badge>
              ))}
            </div>
            <p className="text-sm text-muted-foreground">
              Skills in this summary are self-reported. Independently verified
              evidence requires separate scoped consent. Private compensation
              expectations are never displayed.
            </p>
          </div>
        </SheetContent>
      </Sheet>
    </article>
  )
}
