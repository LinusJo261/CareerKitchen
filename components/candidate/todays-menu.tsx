'use client'

import { useState } from 'react'
import Link from 'next/link'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ArrowUpRight, BadgeCheck, Check, MapPin, Utensils } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Separator } from '@/components/ui/separator'
import { WorkspaceSkeleton } from '@/components/workspace/kit'
import { useWorkspace } from '@/lib/workspace'
import type { Opportunity } from '@/lib/contracts'

type View = 'deciding' | 'interested' | 'passed'

const views: { value: View; label: string }[] = [
  { value: 'deciding', label: 'To decide' },
  { value: 'interested', label: 'Interested' },
  { value: 'passed', label: 'Passed' },
]

const ticketNo = (id: string) =>
  `#${(id.replace(/\D/g, '') || '0').padStart(3, '0')}`

export function TodaysMenu() {
  const { data, execute, isLoading } = useWorkspace()
  const [view, setView] = useState<View>('deciding')
  const [openId, setOpenId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const reduce = useReducedMotion()

  if (isLoading || !data) return <WorkspaceSkeleton />

  const active = data.opportunities.filter((o) => o.status === 'Active')
  const capacity = data.profile.capacity
  const byView = {
    deciding: active.filter((o) => !data.decisions[o.id]).slice(0, capacity),
    interested: active.filter((o) => data.decisions[o.id] === 'interested'),
    passed: active.filter((o) => data.decisions[o.id] === 'passed'),
  }
  const dishes = byView[view]
  const open = active.find((o) => o.id === openId) ?? null

  async function decide(o: Opportunity, value: 'interested' | 'passed') {
    if (busy || !o.decisionId) return
    setBusy(true)
    const saved = await execute(
      'decision.answer',
      {
        id: o.decisionId,
        interested: value === 'interested',
        expected_cycle_version: o.cycleVersion,
        decision_token: o.decisionToken,
      },
      value === 'interested'
        ? `Interest sent to ${o.company}. It becomes an introduction only if they choose you too.`
        : `${o.title} cleared from your menu. Your preferences are unchanged.`,
    )
    if (saved) setOpenId(null)
    setBusy(false)
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-[minmax(0,1fr)_260px] lg:gap-14">
      <section
        aria-labelledby="menu-title"
        className="paper-sheet relative min-w-0 border bg-card px-6 py-10 md:px-12 md:py-14"
      >
        <header className="flex flex-col items-center gap-4 text-center">
          <p className="eyebrow">
            Today&apos;s Menu · Prepared for {data.profile.name.split(' ')[0]}
          </p>
          <h1
            id="menu-title"
            className="display text-5xl text-balance md:text-6xl"
          >
            A short menu,{' '}
            <em className="text-paprika-ink">chosen with care.</em>
          </h1>
          <p className="max-w-md text-pretty text-muted-foreground">
            Each dish was selected against your stated priorities. You set a
            capacity of {capacity}, so you will never see more than {capacity}{' '}
            at once.
          </p>
          <div className="double-rule mt-2 w-full" />
        </header>

        <div className="my-8 flex justify-center">
          <ToggleGroup
            type="single"
            variant="outline"
            value={view}
            onValueChange={(v) => v && setView(v as View)}
            aria-label="Filter your menu"
          >
            {views.map((v) => (
              <ToggleGroupItem
                key={v.value}
                value={v.value}
                className="font-mono text-xs tracking-wider uppercase"
              >
                {v.label}
                <span className="ml-1.5 text-muted-foreground">
                  {byView[v.value].length}
                </span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>

        {dishes.length === 0 ? (
          <MenuEmpty view={view} onReset={() => setView('deciding')} />
        ) : (
          <ol className="flex flex-col">
            <AnimatePresence initial={false} mode="popLayout">
              {dishes.map((o, i) => (
                <motion.li
                  key={o.id}
                  layout={!reduce}
                  initial={reduce ? false : { opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduce ? { opacity: 0 } : { opacity: 0, x: 40 }}
                  transition={{
                    duration: 0.35,
                    ease: [0.2, 0.7, 0.2, 1],
                    delay: reduce ? 0 : i * 0.04,
                  }}
                >
                  {i > 0 && <div className="rule-dashed my-8" />}
                  <Dish
                    opportunity={o}
                    decision={data.decisions[o.id]}
                    onOpen={() => setOpenId(o.id)}
                    onDecide={(v) => decide(o, v)}
                    disabled={busy || !o.decisionId || !o.decisionToken}
                  />
                </motion.li>
              ))}
            </AnimatePresence>
          </ol>
        )}

        <footer className="mt-12 flex flex-col items-center gap-1 text-center">
          <div className="double-rule mb-4 w-full" />
          <p className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
            {data.context.mode === 'local'
              ? 'Local development · Seeded test roles'
              : 'Prepared from your current preferences'}
          </p>
        </footer>
      </section>

      <aside className="flex flex-col gap-8 lg:pt-14">
        <KitchenNote title="How a dish reaches you">
          Employers write a recipe for each role. We only plate roles where your
          must-haves and theirs can both be met.
        </KitchenNote>
        <KitchenNote title="What “interested” means">
          Interest is private until it&apos;s mutual. Nothing is shared with an
          employer beyond your consented profile.
        </KitchenNote>
        <KitchenNote title="Change the menu">
          Your priorities shape every dish.
          <Link
            href="/candidate/profile"
            className="mt-2 flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline"
          >
            Adjust your preferences <ArrowUpRight className="size-3.5" />
          </Link>
        </KitchenNote>
      </aside>

      <Sheet open={!!open} onOpenChange={(v) => !v && setOpenId(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          {open && (
            <>
              <SheetHeader className="gap-2 border-b p-6">
                <p className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
                  Order {ticketNo(open.id)} · {open.employmentType}
                </p>
                <SheetTitle className="font-serif text-3xl font-normal">
                  {open.title}
                </SheetTitle>
                <SheetDescription>
                  {open.company} · {open.location} · {open.arrangement}
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-6 p-6">
                <p className="text-pretty">{open.summary}</p>
                <div>
                  <h3 className="eyebrow mb-2">Why it&apos;s on your menu</h3>
                  <p className="font-serif text-lg italic text-pretty">
                    {open.reason}
                  </p>
                </div>
                {open.responsibilities?.length ? (
                  <div>
                    <h3 className="eyebrow mb-3">What you&apos;d cook</h3>
                    <ul className="flex flex-col gap-2 text-sm">
                      {open.responsibilities.map((r) => (
                        <li key={r} className="flex gap-2">
                          <span aria-hidden className="text-paprika-ink">
                            —
                          </span>
                          {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <dl className="grid grid-cols-2 gap-4 border-y py-4 text-sm">
                  <div>
                    <dt className="eyebrow mb-1">Compensation</dt>
                    <dd>{open.salary}</dd>
                  </div>
                  <div>
                    <dt className="eyebrow mb-1">Reply by</dt>
                    <dd>{open.deadline}</dd>
                  </div>
                </dl>
                <DecisionBar
                  disabled={busy || !open.decisionId || !open.decisionToken}
                  decision={data.decisions[open.id]}
                  onDecide={(v) => decide(open, v)}
                />
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function Dish({
  opportunity: o,
  decision,
  onOpen,
  onDecide,
  disabled,
}: {
  opportunity: Opportunity
  decision?: 'interested' | 'passed'
  onOpen: () => void
  onDecide: (v: 'interested' | 'passed') => void
  disabled?: boolean
}) {
  return (
    <article className="flex flex-col gap-4">
      <div className="flex items-baseline gap-3 font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
        <span>{ticketNo(o.id)}</span>
        <span className="flex items-center gap-1">
          {o.company}
          {o.verified && (
            <BadgeCheck
              className="size-3.5 text-primary"
              aria-label="Employer verified"
            />
          )}
        </span>
        {o.employerInterested && (
          <span className="text-paprika-ink">· They asked for you</span>
        )}
      </div>

      <div className="flex items-baseline gap-3">
        <h2 className="font-serif text-2xl leading-tight md:text-3xl">
          <button
            onClick={onOpen}
            className="text-left underline-offset-4 decoration-1 hover:underline"
          >
            {o.title}
          </button>
        </h2>
        <span className="leader hidden sm:block" aria-hidden />
        <span className="hidden shrink-0 font-mono text-sm sm:block">
          {o.salary}
        </span>
      </div>

      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
        <span className="flex items-center gap-1">
          <MapPin className="size-3.5" />
          {o.location}
        </span>
        <span>{o.arrangement}</span>
        <span className="sm:hidden">{o.salary}</span>
      </p>

      <p className="max-w-prose font-serif text-lg italic text-pretty">
        {o.reason}
      </p>

      <p className="font-mono text-xs text-muted-foreground">
        <span className="sr-only">Key skills: </span>
        {o.skills.join(' · ')}
      </p>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <DecisionBar
          decision={decision}
          onDecide={onDecide}
          compact
          disabled={disabled}
        />
        <Button variant="link" className="px-2" onClick={onOpen}>
          Read the full order <ArrowUpRight data-icon="inline-end" />
        </Button>
      </div>
    </article>
  )
}

function DecisionBar({
  decision,
  onDecide,
  compact,
  disabled,
}: {
  decision?: 'interested' | 'passed'
  onDecide: (v: 'interested' | 'passed') => void
  compact?: boolean
  disabled?: boolean
}) {
  if (decision) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={
            decision === 'interested'
              ? 'stamp border-primary text-primary'
              : 'stamp border-muted-foreground text-muted-foreground'
          }
        >
          {decision === 'interested' ? 'Interest sent' : 'Passed'}
        </span>
      </div>
    )
  }
  return (
    <div className={compact ? 'flex gap-2' : 'flex gap-2 [&>*]:flex-1'}>
      <Button disabled={disabled} onClick={() => onDecide('interested')}>
        <Check data-icon="inline-start" /> I&apos;m interested
      </Button>
      <Button
        disabled={disabled}
        variant="outline"
        onClick={() => onDecide('passed')}
      >
        Pass
      </Button>
    </div>
  )
}

function KitchenNote({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-2 border-t pt-4">
      <h2 className="font-sans text-sm font-medium tracking-normal">{title}</h2>
      <div className="text-sm leading-relaxed text-muted-foreground">
        {children}
      </div>
    </section>
  )
}

function MenuEmpty({ view, onReset }: { view: View; onReset: () => void }) {
  const copy = {
    deciding: {
      title: 'Nothing left to decide today.',
      body: 'New dishes are plated when a role fits your priorities. We will not pad the menu.',
    },
    interested: {
      title: 'No interest sent yet.',
      body: 'When you mark a role as interesting, it waits here until the employer chooses too.',
    },
    passed: {
      title: 'Nothing passed in this view.',
      body: 'Decisions are recorded by the backend. New introductions appear only when they are eligible.',
    },
  }[view]
  return (
    <Empty className="py-12">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Utensils />
        </EmptyMedia>
        <EmptyTitle className="font-serif text-2xl font-normal">
          {copy.title}
        </EmptyTitle>
        <EmptyDescription>{copy.body}</EmptyDescription>
      </EmptyHeader>
      {view !== 'deciding' && (
        <EmptyContent>
          <Button variant="outline" onClick={onReset}>
            Back to today&apos;s menu
          </Button>
        </EmptyContent>
      )}
      <Separator className="sr-only" />
    </Empty>
  )
}
