import Image from 'next/image'
import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Brand } from './brand'
import { ProvenanceGlyph, ProvenanceLegend } from './pass/provenance'
import { cn } from '@/lib/utils'

const courses = [
  {
    station: 'Mise en Place',
    title: 'Everyone preps first.',
    text: 'Candidates set out what they want and what they will not compromise on. Employers write the recipe: requirements, preferences, and real constraints.',
  },
  {
    station: 'The Pass',
    title: 'A short rail, not an endless feed.',
    text: 'Each side reviews a limited set of introductions. Active decision ceilings keep the next step focused and manageable.',
  },
  {
    station: 'Taste Test',
    title: 'Evidence with a purpose.',
    text: 'Candidates submit factual claims for independent review and choose which employer and role may receive verified evidence.',
  },
  {
    station: 'The Table',
    title: 'Introductions, when both say yes.',
    text: 'Nobody is introduced until both sides opt in. Then the conversation moves to the table.',
  },
]

const demoLines: {
  label: string
  status: 'confirmed' | 'inferred' | 'unknown'
  word: string
}[] = [
  { label: 'Ships design systems', status: 'confirmed', word: 'Yes' },
  { label: 'B2B SaaS experience', status: 'inferred', word: 'Yes' },
  { label: 'Hybrid, 2 days NYC', status: 'unknown', word: '?' },
]

function SampleTicket({
  className,
  name,
  title,
  stamp,
}: {
  className?: string
  name: string
  title: string
  stamp: 'Ready' | 'To verify'
}) {
  return (
    <div className={cn('ticket-shadow relative w-60 shrink-0 pt-4', className)}>
      <span
        aria-hidden="true"
        className="absolute top-0 left-1/2 z-10 h-6 w-12 -translate-x-1/2 rounded-b-[3px] bg-steel"
      />
      <div className="ticket px-5 pt-7 pb-5">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
            Sample
          </span>
          <span
            className={cn(
              'stamp',
              stamp === 'Ready'
                ? 'border-primary text-primary'
                : 'border-paprika-ink text-paprika-ink',
            )}
          >
            {stamp}
          </span>
        </div>
        <p className="mt-2 font-serif text-2xl leading-tight">{name}</p>
        <p className="text-sm text-muted-foreground">{title}</p>
        <div className="rule-dashed my-4" />
        <ul className="flex flex-col gap-2">
          {demoLines.map((l, i) => (
            <li key={l.label} className="flex items-center gap-2.5 text-sm">
              <span
                className={
                  l.status === 'unknown'
                    ? 'text-muted-foreground'
                    : 'text-primary'
                }
              >
                <ProvenanceGlyph
                  status={stamp === 'Ready' && i === 2 ? 'confirmed' : l.status}
                />
              </span>
              <span className="flex-1 truncate">{l.label}</span>
              <span className="font-mono text-xs">
                {stamp === 'Ready' && i === 2 ? 'Yes' : l.word}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export function Landing() {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:bg-card focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="page-width flex h-20 items-center justify-between gap-6">
        <Brand />
        <nav
          aria-label="Main"
          className="hidden items-center gap-8 text-sm md:flex"
        >
          <a href="#service" className="hover:text-primary">
            How service works
          </a>
          <a href="#candidates" className="hover:text-primary">
            For candidates
          </a>
          <a href="#employers" className="hover:text-primary">
            For employers
          </a>
        </nav>
        <div className="flex items-center gap-2">
          <Button variant="ghost" asChild>
            <Link href="/sign-in">Sign in</Link>
          </Button>
          <Button asChild>
            <Link href="/get-started">Get started</Link>
          </Button>
        </div>
      </header>

      <main id="main">
        <section
          aria-labelledby="hero"
          className="page-width pt-10 pb-20 md:pt-16"
        >
          <div className="flex items-center gap-4 font-mono text-[11px] tracking-[0.16em] text-muted-foreground uppercase">
            <span>Front of House</span>
            <span className="h-px flex-1 bg-border" aria-hidden="true" />
            <span>Now seating</span>
          </div>
          <h1
            id="hero"
            className="display mt-8 text-[clamp(3.4rem,10vw,9.5rem)] leading-[0.88] text-balance"
          >
            Fewer plates.
            <br />
            <span className="text-primary italic">Better</span> service.
          </h1>
          <div className="mt-10 grid gap-10 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] md:items-end">
            <p className="max-w-md text-lg leading-relaxed text-pretty">
              Career Kitchen is a two-sided matching kitchen. Instead of a board
              with a thousand listings, each side receives a small set of
              mutually relevant introductions — prepared, checked, and sent to
              the pass.
            </p>
            <div className="flex flex-wrap gap-3 md:justify-end">
              <Button size="lg" asChild>
                <Link href="/get-started">
                  Find your next role
                  <ArrowRight data-icon="inline-end" />
                </Link>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <Link href="/employer/pass">Open employer workspace</Link>
              </Button>
            </div>
          </div>
        </section>

        <section aria-label="The kitchen" className="relative">
          <div className="page-width">
            <div className="relative aspect-[16/7] overflow-hidden rounded-sm border">
              <Image
                src="/images/the-pass.png"
                alt="Order tickets clipped to a steel rail above a kitchen pass"
                fill
                priority
                sizes="(min-width: 1280px) 1200px, 100vw"
                className="object-cover"
              />
            </div>
          </div>
        </section>

        <section
          id="service"
          aria-labelledby="service-title"
          className="page-width py-24"
        >
          <div className="grid gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div>
              <p className="eyebrow">The menu of service</p>
              <h2
                id="service-title"
                className="mt-3 text-5xl leading-tight text-balance"
              >
                How a match leaves the kitchen.
              </h2>
            </div>
            <ol className="flex flex-col">
              {courses.map((c) => (
                <li
                  key={c.station}
                  className="grid gap-2 border-t py-6 md:grid-cols-[160px_minmax(0,1fr)]"
                >
                  <p className="font-mono text-[11px] tracking-[0.14em] text-paprika-ink uppercase">
                    {c.station}
                  </p>
                  <div>
                    <h3 className="font-serif text-2xl">{c.title}</h3>
                    <p className="mt-1 leading-relaxed text-muted-foreground">
                      {c.text}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section
          id="employers"
          aria-labelledby="employers-title"
          className="bg-primary text-primary-foreground"
        >
          <div className="page-width grid gap-12 py-24 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:items-center">
            <div>
              <p className="font-mono text-[11px] tracking-[0.16em] uppercase opacity-75">
                For employers · The Pass
              </p>
              <h2
                id="employers-title"
                className="mt-3 text-5xl leading-tight text-balance"
              >
                Clear role terms. Thoughtful introductions.
              </h2>
              <p className="mt-5 max-w-md leading-relaxed opacity-85">
                Review the people introduced for your roles, record your
                decisions, and move forward when interest is mutual. Evidence
                sharing requires the candidate’s consent.
              </p>
              <ProvenanceLegend className="mt-6 text-primary-foreground/80 [&_dt]:text-primary-foreground" />
              <Button variant="secondary" size="lg" className="mt-8" asChild>
                <Link href="/employer/pass">
                  Open employer workspace
                  <ArrowRight data-icon="inline-end" />
                </Link>
              </Button>
            </div>
            <div className="text-foreground" aria-hidden="true">
              <div className="rail" />
              <div className="-mt-1 flex justify-center gap-5 overflow-hidden px-2">
                <SampleTicket
                  name="Maya Chen"
                  title="Product Designer"
                  stamp="Ready"
                  className="-rotate-1"
                />
                <SampleTicket
                  name="Daniel Okafor"
                  title="Senior Designer"
                  stamp="To verify"
                  className="hidden rotate-1 sm:block"
                />
              </div>
            </div>
          </div>
        </section>

        <section
          id="candidates"
          aria-labelledby="candidates-title"
          className="page-width grid gap-12 py-24 md:grid-cols-2"
        >
          <div>
            <p className="eyebrow">For candidates · Today&apos;s Menu</p>
            <h2
              id="candidates-title"
              className="mt-3 text-5xl leading-tight text-balance"
            >
              A short menu, chosen for you.
            </h2>
          </div>
          <div className="flex flex-col gap-5">
            <p className="text-lg leading-relaxed text-pretty">
              No infinite scroll, no applying into silence. You see a handful of
              roles that fit what you told us — with the reasons written out —
              and say yes only to the ones you want.
            </p>
            <ul className="flex flex-col border-t">
              {[
                'Your compensation minimum stays private',
                'You choose which verified evidence to share for each role',
                'Introductions need both sides to say yes',
              ].map((t) => (
                <li key={t} className="flex gap-3 border-b py-3 text-sm">
                  <span className="mt-1.5 text-primary">
                    <ProvenanceGlyph status="confirmed" />
                  </span>
                  {t}
                </li>
              ))}
            </ul>
            <Button size="lg" className="self-start" asChild>
              <Link href="/candidate/opportunities">
                Open candidate workspace
                <ArrowRight data-icon="inline-end" />
              </Link>
            </Button>
          </div>
        </section>
      </main>

      <footer className="double-rule">
        <div className="page-width flex flex-wrap items-center justify-between gap-4 py-8 text-sm text-muted-foreground">
          <Brand />
          <p>
            Illustrations use fictional examples. Workspace changes are saved to
            your account.
          </p>
        </div>
      </footer>
    </>
  )
}
