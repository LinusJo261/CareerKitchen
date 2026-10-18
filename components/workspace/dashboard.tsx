'use client'

import Link from 'next/link'
import {
  ArrowRight,
  ArrowUpRight,
  Sparkles,
  CalendarDays,
  Clock3,
  Check,
  ShieldCheck,
  BriefcaseBusiness,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { CompanyMark } from '@/components/brand'
import { Initials, PageHeader } from './kit'
import { OpportunityCard, CandidateCard } from './opportunities'
import { useWorkspace } from '@/lib/workspace'
import type { Role } from '@/lib/contracts'

export function Dashboard({ role }: { role: Role }) {
  const { data } = useWorkspace()
  const employer = role === 'employer'
  const pending = data.opportunities
    .filter((o) => o.status === 'Active' && !data.decisions[o.id])
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
  const interviews = data.interviews
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
  const nextInterview = interviews[0]
  const nextDate = nextInterview
    ? new Date(
        nextInterview.startAt ??
          nextInterview.slots?.find(
            (slot) => new Date(slot.start_at) > new Date(),
          )?.start_at ??
          `${nextInterview.date}T12:00:00`,
      )
    : null
  const reviewPath = employer ? '/employer/pass' : '/candidate/opportunities'

  const stats = [
    {
      value: employer ? pendingCandidates.length : pending.length,
      label: employer ? 'Candidates to review' : 'Ready for your decision',
      href: reviewPath,
    },
    {
      value: waiting,
      label: employer ? 'Introduction requests' : 'Awaiting a response',
      href: reviewPath,
    },
    {
      value: matches.length,
      label: 'Mutual introductions',
      href: `/${role}/${employer ? 'pipeline' : 'matches'}`,
    },
    {
      value: interviews.length,
      label: 'Upcoming interviews',
      href: `/${role}/interviews`,
    },
  ]

  return (
    <div className="rise">
      <PageHeader
        eyebrow={employer ? data.organization.name : 'Your next chapter'}
        title={
          employer
            ? 'Good people make great teams.'
            : data.profile.name.trim()
              ? `Welcome back, ${data.profile.name.trim().split(/\s+/)[0]}.`
              : 'Your next chapter starts here.'
        }
        description={
          employer
            ? `Here’s what’s moving forward at ${data.organization.name}.`
            : 'A few good opportunities. A little forward momentum.'
        }
        actions={
          <Button variant="outline" asChild>
            <Link
              href={employer ? '/employer/vacancies' : '/candidate/profile'}
            >
              {employer ? <BriefcaseBusiness data-icon="inline-start" /> : null}
              {employer ? 'Manage job openings' : 'Your preferences'}
              <ArrowUpRight data-icon="inline-end" />
            </Link>
          </Button>
        }
      />

      <div className="mb-8 grid grid-cols-2 overflow-hidden rounded-md border bg-card md:grid-cols-4">
        {stats.map((stat, index) => (
          <div
            key={stat.label}
            className={`${index >= 2 ? 'border-t md:border-t-0' : ''} ${index % 2 ? 'border-l' : index > 0 ? 'md:border-l' : ''}`}
          >
            <Link
              href={stat.href}
              className="flex h-full flex-col gap-2 p-4 transition-colors hover:bg-muted sm:p-6"
            >
              <span
                className={`font-serif text-3xl leading-tight ${index === 0 ? 'text-primary' : ''}`}
              >
                {String(stat.value).padStart(2, '0')}
              </span>
              <span className="text-xs text-muted-foreground">
                {stat.label}
              </span>
            </Link>
          </div>
        ))}
      </div>

      <div className="workspace-grid">
        <div className="min-w-0">
          <section aria-labelledby="dashboard-review">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <h2 id="dashboard-review" className="text-xl">
                  {employer
                    ? 'People worth meeting'
                    : 'Your next possibilities'}
                </h2>
                <Badge variant="secondary">
                  {employer ? pendingCandidates.length : pending.length} to
                  review
                </Badge>
              </div>
              <Link
                href={reviewPath}
                className="inline-flex items-center gap-1 py-2 text-xs text-primary"
              >
                View all <ArrowRight aria-hidden="true" className="size-3.5" />
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
                <Check
                  aria-hidden="true"
                  className="mx-auto mb-3 size-7 text-primary"
                />
                <h3 className="font-serif text-xl">You’re all caught up.</h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  New introductions will appear when they are available.
                </p>
              </div>
            )}
          </section>

          <section className="mt-8" aria-labelledby="dashboard-progress">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h2 id="dashboard-progress" className="text-xl">
                Moving forward
              </h2>
              <Link
                href={`/${role}/${employer ? 'pipeline' : 'matches'}`}
                className="inline-flex items-center gap-1 py-2 text-xs text-primary"
              >
                View introductions{' '}
                <ArrowRight aria-hidden="true" className="size-3.5" />
              </Link>
            </div>
            <div className="panel divide-y">
              {matches.map((match) => (
                <Link
                  key={match.id}
                  href={`/${role}/messages`}
                  className="flex flex-wrap items-center gap-4 p-5 transition-colors hover:bg-muted"
                >
                  {employer ? (
                    <Initials name={match.name} />
                  ) : (
                    <CompanyMark name={match.company} />
                  )}
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-medium">
                      {employer ? match.name : match.role}
                    </h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {employer ? match.role : match.company} · Updated{' '}
                      {match.updated.toLowerCase()}
                    </p>
                  </div>
                  <Badge variant="secondary">{match.stage}</Badge>
                  <ArrowUpRight
                    aria-hidden="true"
                    className="size-4 text-muted-foreground"
                  />
                </Link>
              ))}
              {matches.length === 0 && (
                <p className="p-5 text-sm text-muted-foreground">
                  When both sides share interest, your introduction appears
                  here.
                </p>
              )}
            </div>
          </section>
        </div>

        <aside className="flex min-w-0 flex-col gap-5">
          <section className="panel p-5">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="font-sans text-sm font-medium tracking-normal">
                Coming up next
              </h2>
              <CalendarDays
                aria-hidden="true"
                className="size-4 text-muted-foreground"
              />
            </div>
            {nextInterview && nextDate ? (
              <>
                <div className="mb-4 flex items-center gap-3">
                  <div
                    aria-hidden="true"
                    className="flex size-12 shrink-0 flex-col items-center justify-center rounded-md bg-accent text-accent-foreground"
                  >
                    <span className="text-[10px] font-medium uppercase">
                      {nextDate.toLocaleString('en-US', { month: 'short' })}
                    </span>
                    <span className="text-lg font-medium">
                      {nextDate.getDate()}
                    </span>
                  </div>
                  <div>
                    <p className="text-sm font-medium">
                      {employer ? nextInterview.person : nextInterview.company}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {nextInterview.role}
                    </p>
                  </div>
                </div>
                <p className="flex items-start gap-2 text-xs text-muted-foreground">
                  <Clock3 aria-hidden="true" className="size-3.5 shrink-0" />
                  <span>
                    <time dateTime={nextInterview.date}>
                      {nextDate.toLocaleDateString('en-US', {
                        weekday: 'long',
                        month: 'short',
                        day: 'numeric',
                      })}
                    </time>{' '}
                    · {nextInterview.time}
                  </span>
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {nextInterview.proposalStatus === 'PROPOSED'
                    ? 'Interview times proposed'
                    : nextInterview.format}
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
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Nothing scheduled yet. Agreed conversations will appear here.
              </p>
            )}
          </section>
          <section className="rounded-md border border-primary/15 bg-secondary p-5 text-secondary-foreground">
            <ShieldCheck aria-hidden="true" className="mb-4 size-6" />
            <h2 className="text-lg">
              {employer
                ? 'Clarity before commitment.'
                : 'Good things take alignment.'}
            </h2>
            <p className="mt-2 text-sm opacity-80">
              {employer
                ? 'Set the terms upfront. Help both sides move forward with confidence.'
                : 'Your priorities shape your introductions. Keep them up to date as your next chapter takes shape.'}
            </p>
            <Link
              href={`/${role}/${employer ? 'pact' : 'profile'}`}
              className="mt-5 inline-flex items-center gap-2 text-sm font-medium"
            >
              {employer
                ? 'Review agreement terms'
                : 'Fine-tune your preferences'}
              <ArrowRight aria-hidden="true" className="size-4" />
            </Link>
          </section>
          <section className="px-1 py-3">
            <h2 className="mb-3 flex items-center gap-2 font-sans text-sm font-medium tracking-normal">
              <Sparkles aria-hidden="true" className="size-4 text-primary" />
              {employer
                ? 'A little clarity goes a long way'
                : 'Your pace. Your possibilities.'}
            </h2>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {employer
                ? 'Review hiring conditions to help your team make informed decisions.'
                : `You’ve chosen up to ${data.profile.capacity} active opportunities at a time. More focus, without closing doors.`}
            </p>
            <Link
              href={`/${role}/${employer ? 'witness' : 'profile'}`}
              className="mt-3 inline-flex items-center gap-1 py-1 text-xs text-primary"
            >
              {employer ? 'Review next steps' : 'Manage your capacity'}{' '}
              <ArrowRight aria-hidden="true" className="size-3" />
            </Link>
          </section>
        </aside>
      </div>
    </div>
  )
}
