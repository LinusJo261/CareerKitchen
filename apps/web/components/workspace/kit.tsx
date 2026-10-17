'use client'
import type { LucideIcon } from 'lucide-react'
import { Check } from 'lucide-react'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="rise mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        {eyebrow && <p className="eyebrow mb-3">{eyebrow}</p>}
        <h1 className="text-4xl font-normal text-balance md:text-5xl">{title}</h1>
        {description && <p className="mt-3 text-pretty text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SectionTitle({ title, description, action }: { title: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-lg font-medium tracking-tight">{title}</h2>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  )
}

export function EmptyNote({ icon: Icon, title, description, children }: { icon: LucideIcon; title: string; description: string; children?: React.ReactNode }) {
  return (
    <Empty className="panel border-solid py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon"><Icon /></EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      {children && <EmptyContent>{children}</EmptyContent>}
    </Empty>
  )
}

/** Horizontal progression used for matches, PACT readiness, and wizards. */
export function Progression({ steps, current, className }: { steps: readonly string[]; current: number; className?: string }) {
  return (
    <ol className={cn('flex items-center gap-2', className)} aria-label="Progress">
      {steps.map((step, i) => {
        const done = i < current
        const active = i === current
        return (
          <li key={step} className="flex flex-1 items-center gap-2" aria-current={active ? 'step' : undefined}>
            <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-medium transition-colors', done && 'border-primary bg-primary text-primary-foreground', active && 'border-primary text-primary', !done && !active && 'text-muted-foreground')}>
              {done ? <Check className="size-3.5" /> : i + 1}
            </span>
            <span className={cn('hidden text-xs whitespace-nowrap md:inline', active ? 'font-medium text-foreground' : 'text-muted-foreground')}>{step}</span>
            {i < steps.length - 1 && <span className={cn('connection-line', done && 'bg-primary')} />}
          </li>
        )
      })}
    </ol>
  )
}

export function WorkspaceSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading workspace" className="flex flex-col gap-6">
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-64 rounded-xl" />)}
      </div>
    </div>
  )
}

export function Initials({ name, className }: { name: string; className?: string }) {
  return (
    <span aria-hidden="true" className={cn('flex size-10 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-medium text-accent-foreground', className)}>
      {name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
    </span>
  )
}
