'use client'

import Link from 'next/link'
import {
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  Clock3,
  Check,
  ShieldCheck,
  Plus,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { CompanyMark } from '@/components/brand'
import { OpportunityCard, CandidateCard } from './opportunities'
import { useWorkspace } from '@/lib/workspace'
import type { Role } from '@/lib/contracts'

export function Dashboard({ role }: { role: Role }) {
  const { data } = useWorkspace()
  const employer = role === 'employer'
  const pending = data.opportunities
    .filter(
      (opportunity) =>
        opportunity.status === 'Active' && !data.decisions[opportunity.id],
    )
    .slice(0, data.profile.capacity)
  const pendingCandidates = data.candidates.filter(
    (candidate) => !data.candidateDecisions[candidate.id],
  )
  const matches = data.matches.filter(
    (match) => match.status === 'ACTIVE' && !match.state?.startsWith('CLOSED'),
  )
  const waiting = Object.values(
    employer ? data.candidateDecisions : data.decisions,
  ).filter((decision) => decision === 'interested').length
  const upcoming = data.interviews
    .filter(
      (interview) =>
        interview.side === role &&
        (interview.proposalStatus === 'PROPOSED'
          ? interview.slots?.some(
              (slot) => new Date(slot.start_at) > new Date(),
            )
          : !!interview.startAt && new Date(interview.startAt) > new Date()),
    )
    .toSorted((a, b) =>
      (a.startAt ?? a.slots?.[0]?.start_at ?? a.date).localeCompare(
        b.startAt ?? b.slots?.[0]?.start_at ?? b.date,
      ),
    )
  const next = upcoming[0]
  const nextDate = next
    ? new Date(
        next.startAt ??
          next.slots?.find((slot) => new Date(slot.start_at) > new Date())
            ?.start_at ??
          `${next.date}T12:00:00`,
      )
    : null

  return (
    <div className="rise">
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-sm text-muted-foreground">
            YOUR NEXT CHAPTER
          </p>
          <h1 className="text-3xl font-medium md:text-4xl">
            {employer
              ? 'Good people make great teams.'
              : 'Your next chapter starts here.'}
          </h1>
          <p className="mt-3 text-sm text-muted-foreground">
            {employer
              ? `Here’s what’s moving forward at ${data.organization.name}.`
              : 'A few good opportunities. A little forward momentum.'}
          </p>
        </div>
        <Button variant="outline" asChild>
          <Link href={employer ? '/employer/vacancies' : '/candidate/profile'}>
            {employer && <Plus data-icon="inline-start" />}
            {employer ? 'Create a vacancy' : 'Your preferences'}
            {!employer && <ArrowUpRight data-icon="inline-end" />}
          </Link>
        </Button>
      </div>
      <div className="mb-8 grid grid-cols-2 gap-y-5 rounded-xl border bg-card py-6 md:grid-cols-4">
        {[
          {
            value: employer ? pendingCandidates.length : pending.length,
            label: employer
              ? 'Candidates to review'
              : 'Ready for your decision',
            href: employer ? 'candidates' : 'opportunities',
            active: true,
          },
          {
            value: waiting,
            label: 'Awaiting a response',
            href: employer ? 'candidates' : 'opportunities',
          },
          {
            value: matches.length,
            label: 'Mutual matches',
            href: employer ? 'pipeline' : 'matches',
          },
          {
            value: upcoming.length,
            label: 'Upcoming interviews',
            href: 'interviews',
          },
        ].map((stat, index) => (
          <Link
            href={`/${role}/${stat.href}`}
            key={stat.label}
            className={`px-6 ${index ? 'border-l' : ''}`}
          >
            <div className="mb-2 flex items-center gap-2">
              <span
                className={`text-3xl font-medium tracking-tight ${stat.active ? 'text-primary' : ''}`}
              >
                {String(stat.value).padStart(2, '0')}
              </span>
              {stat.active && (
                <span className="size-1.5 rounded-full bg-orange" />
              )}
            </div>
            <span className="text-xs text-muted-foreground">{stat.label}</span>
          </Link>
        ))}
      </div>
      <div className="workspace-grid">
        <div className="min-w-0">
          <section>
            <div className="mb-5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-medium">
                  {employer
                    ? 'People worth meeting'
                    : 'Your next possibilities'}
                </h2>
                <Badge variant="secondary">
                  {employer ? pendingCandidates.length : pending.length} ready
                </Badge>
              </div>
              <Link
                href={`/${role}/${employer ? 'candidates' : 'opportunities'}`}
                className="flex items-center gap-1 text-xs text-muted-foreground"
              >
                View all <ArrowRight className="size-3.5" />
              </Link>
            </div>
            <p className="mb-5 text-sm text-muted-foreground">
              {employer
                ? 'Review the candidates delivered for your open roles.'
                : 'Review the opportunities delivered around your profile and preferences.'}
            </p>
            <div className="grid gap-4 2xl:grid-cols-2">
              {employer
                ? pendingCandidates
                    .slice(0, 2)
                    .map((candidate) => (
                      <CandidateCard key={candidate.id} candidate={candidate} />
                    ))
                : pending
                    .slice(0, 2)
                    .map((opportunity) => (
                      <OpportunityCard
                        key={opportunity.id}
                        opportunity={opportunity}
                        compact
                      />
                    ))}
            </div>
            {(employer ? pendingCandidates : pending).length === 0 && (
              <div className="panel p-10 text-center">
                <Check className="mx-auto mb-3 size-7 text-primary" />
                <h3 className="text-lg">No decisions waiting.</h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  New introductions will appear when they are available.
                </p>
              </div>
            )}
          </section>
          <section className="mt-8">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-xl font-medium">Moving forward</h2>
              <Link
                href={`/${role}/${employer ? 'pipeline' : 'matches'}`}
                className="text-xs text-muted-foreground"
              >
                View matches <ArrowRight className="inline size-3.5" />
              </Link>
            </div>
            <div className="panel divide-y">
              {matches.length === 0 ? (
                <p className="p-5 text-sm text-muted-foreground">
                  Mutual introductions will appear here once both sides express
                  interest.
                </p>
              ) : (
                matches.map((match) => (
                  <Link
                    key={match.id}
                    href={`/${role}/messages`}
                    className="flex flex-wrap items-center gap-4 p-5 hover:bg-muted"
                  >
                    <CompanyMark name={match.company} />
                    <div className="flex-1">
                      <h3 className="text-sm font-medium tracking-normal">
                        {match.role}
                      </h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {employer ? match.name : match.company}
                      </p>
                    </div>
                    <Badge variant="secondary">{match.stage}</Badge>
                    <ArrowUpRight className="size-4 text-muted-foreground" />
                  </Link>
                ))
              )}
            </div>
          </section>
        </div>
        <aside className="flex flex-col gap-5">
          <section className="panel p-5">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-sm font-medium tracking-normal">
                Coming up next
              </h2>
              <CalendarDays className="size-4 text-muted-foreground" />
            </div>
            {next && nextDate ? (
              <div>
                <div className="mb-4 flex items-center gap-3">
                  <div className="flex size-12 flex-col items-center justify-center rounded-lg bg-accent text-accent-foreground">
                    <span className="text-[10px] font-medium uppercase">
                      {nextDate.toLocaleString([], { month: 'short' })}
                    </span>
                    <span className="text-lg font-medium">
                      {nextDate.getDate()}
                    </span>
                  </div>
                  <div>
                    <p className="text-sm font-medium">
                      {next.proposalStatus === 'PROPOSED'
                        ? 'Interview times proposed'
                        : 'Interview'}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {next.company} · {next.role}
                    </p>
                  </div>
                </div>
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Clock3 className="size-3.5" />
                  {nextDate.toLocaleString([], { weekday: 'long' })},{' '}
                  {next.startAt
                    ? nextDate.toLocaleTimeString([], {
                        hour: 'numeric',
                        minute: '2-digit',
                      })
                    : next.time}
                </p>
                <Button
                  asChild
                  variant="outline"
                  className="mt-5 w-full"
                  size="sm"
                >
                  <Link href={`/${role}/interviews`}>
                    View interview <ArrowUpRight data-icon="inline-end" />
                  </Link>
                </Button>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No upcoming interviews.
              </p>
            )}
          </section>
          <section className="rounded-xl border border-primary/15 bg-secondary p-5 text-secondary-foreground">
            <ShieldCheck className="mb-4 size-6" />
            <h2 className="text-lg font-medium">
              {employer
                ? 'Clarity before commitment.'
                : 'Good things take alignment.'}
            </h2>
            <p className="mt-2 text-sm opacity-80">
              {employer
                ? 'Set the terms upfront. Help both sides move forward with confidence.'
                : 'Your priorities shape every introduction. Keep them up to date as your next chapter takes shape.'}
            </p>
            <Link
              href={`/${role}/${employer ? 'pact' : 'profile'}`}
              className="mt-5 flex items-center gap-2 text-sm font-medium"
            >
              {employer
                ? 'Review agreement terms'
                : 'Fine-tune your preferences'}
              <ArrowRight className="size-4" />
            </Link>
          </section>
          {!employer && (
            <section className="px-1 py-3">
              <h2 className="mb-3 text-sm font-medium tracking-normal">
                Your pace. Your possibilities.
              </h2>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Your active opportunity limit is {data.profile.capacity}. Review
                and update your availability as your plans change.
              </p>
              <Link
                href="/candidate/profile"
                className="mt-3 inline-flex items-center gap-1 text-xs text-primary"
              >
                Manage your capacity <ArrowRight className="size-3" />
              </Link>
            </section>
          )}
        </aside>
      </div>
    </div>
  )
}
