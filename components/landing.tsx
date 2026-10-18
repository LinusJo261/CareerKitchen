import Link from 'next/link'
import { ArrowRight, Check, HeartHandshake, ListFilter, MessageCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Brand } from './brand'
import { ProvenanceGlyph, ProvenanceLegend } from './pass/provenance'
import { cn } from '@/lib/utils'

const courses = [
  {
    station: 'Mise en Place',
    title: 'Everyone preps first.',
    text: 'Start with what matters. Candidates share their goals and must-haves; employers set out the role, requirements, and working arrangements.',
  },
  {
    station: 'The Pass',
    title: 'A short rail, not an endless feed.',
    text: 'Review a small set of possibilities with the reasons behind each one. Keep your attention on the people and roles you actually want to consider.',
  },
  {
    station: 'Taste Test',
    title: 'Ask before you assume.',
    text: 'See which details are stated, which are inferred, and which still need a question. A suggestion is a starting point for a conversation.',
  },
  {
    station: 'The Table',
    title: 'Introductions, when both say yes.',
    text: 'An introduction needs a yes from both sides. Once interest is mutual, take the next step together.',
  },
]

const principles = [
  { icon: ListFilter, title: 'A shorter shortlist', text: 'Make room for the possibilities that matter.' },
  { icon: Check, title: 'Reasons you can read', text: 'Know what is stated and what needs a question.' },
  { icon: HeartHandshake, title: 'A yes from both sides', text: 'Every introduction begins with mutual interest.' },
]

const demoLines: { label: string; status: 'confirmed' | 'inferred' | 'unknown'; word: string }[] = [
  { label: 'Ships design systems', status: 'confirmed', word: 'Yes' },
  { label: 'B2B SaaS experience', status: 'inferred', word: 'Yes' },
  { label: 'Hybrid, 2 days NYC', status: 'unknown', word: '?' },
]

function SampleTicket({ className, name, title, stamp }: { className?: string; name: string; title: string; stamp: 'Ready' | 'To verify' }) {
  return (
    <div className={cn('ticket-shadow relative w-60 shrink-0 pt-4', className)}>
      <span aria-hidden="true" className="absolute top-0 left-1/2 z-10 h-6 w-12 -translate-x-1/2 rounded-b-[3px] bg-steel" />
      <div className="ticket px-5 pt-7 pb-5">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">Sample</span>
          <span className={cn('stamp', stamp === 'Ready' ? 'border-primary text-primary' : 'border-paprika-ink text-paprika-ink')}>{stamp}</span>
        </div>
        <p className="mt-2 font-serif text-2xl leading-tight">{name}</p>
        <p className="text-sm text-muted-foreground">{title}</p>
        <div className="rule-dashed my-4" />
        <ul className="flex flex-col gap-2">
          {demoLines.map((l, i) => (
            <li key={l.label} className="flex items-center gap-2.5 text-sm">
              <span className={l.status === 'unknown' ? 'text-muted-foreground' : 'text-primary'}>
                <ProvenanceGlyph status={stamp === 'Ready' && i === 2 ? 'confirmed' : l.status} />
              </span>
              <span className="flex-1 truncate">{l.label}</span>
              <span className="font-mono text-xs">{stamp === 'Ready' && i === 2 ? 'Yes' : l.word}</span>
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
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:bg-card focus:px-3 focus:py-2">Skip to content</a>
      <header className="page-width flex min-h-20 flex-wrap items-center justify-between gap-x-4 gap-y-3 py-4">
        <Brand />
        <nav aria-label="Main" className="hidden items-center gap-6 text-sm lg:flex">
          <a href="#service" className="hover:text-primary">How service works</a>
          <a href="#candidates" className="hover:text-primary">For candidates</a>
          <a href="#employers" className="hover:text-primary">For employers</a>
        </nav>
        <div className="flex items-center gap-2">
          <Button variant="ghost" className="hidden sm:inline-flex" asChild><Link href="/sign-in">Sign in</Link></Button>
          <Button asChild><Link href="/get-started">Get started<ArrowRight aria-hidden="true" className="hidden sm:block" /></Link></Button>
        </div>
      </header>

      <main id="main">
        <section aria-labelledby="hero" className="page-width pt-8 pb-14 md:pt-16 md:pb-20">
          <div className="flex items-center gap-4 font-mono text-[11px] tracking-[0.16em] text-muted-foreground uppercase">
            <span>Front of House</span>
            <span className="h-px flex-1 bg-border" aria-hidden="true" />
            <span className="whitespace-nowrap">Interactive demo</span>
          </div>
          <h1 id="hero" className="display mt-8 text-[clamp(2.75rem,10.5vw,9.5rem)] leading-[0.92] text-balance">
            Fewer plates.<br />
            <span className="text-primary italic">Better</span> service.
          </h1>
          <div className="mt-10 grid gap-10 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] md:items-end">
            <p className="max-w-md text-lg leading-relaxed text-pretty">
              A calmer way to find your next role — or your next teammate. Explore a small menu of possibilities, with clear reasons and a yes from both sides.
            </p>
            <div className="flex flex-col gap-4 md:items-end">
              <div className="flex flex-wrap gap-3">
                <Button size="lg" asChild><Link href="/onboarding/candidate">Find your next role<ArrowRight aria-hidden="true" data-icon="inline-end" /></Link></Button>
                <Button size="lg" variant="outline" asChild><Link href="/employer/pass">Find your next teammate</Link></Button>
              </div>
              <p className="text-xs text-muted-foreground">Try the experience with fictional sample data. No account needed.</p>
            </div>
          </div>
        </section>

        <section aria-label="A more thoughtful introduction" className="page-width">
          <div className="grid border-y md:grid-cols-3">
            {principles.map(({ icon: Icon, title, text }, i) => (
              <div key={title} className={cn('flex items-start gap-4 py-6 md:py-8', i > 0 && 'border-t md:border-t-0 md:border-l md:pl-7', i < 2 && 'md:pr-7')}>
                <Icon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-primary" strokeWidth={1.5} />
                <div>
                  <h2 className="font-serif text-xl tracking-normal">{title}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">{text}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section id="service" aria-labelledby="service-title" className="page-width py-24">
          <div className="grid gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div>
              <p className="eyebrow">The menu of service</p>
              <h2 id="service-title" className="mt-3 text-5xl leading-tight text-balance">How a match leaves the kitchen.</h2>
            </div>
            <ol className="flex flex-col">
              {courses.map((c) => (
                <li key={c.station} className="grid gap-2 border-t py-6 md:grid-cols-[160px_minmax(0,1fr)]">
                  <p className="font-mono text-[11px] tracking-[0.14em] text-paprika-ink uppercase">{c.station}</p>
                  <div>
                    <h3 className="font-serif text-2xl">{c.title}</h3>
                    <p className="mt-1 leading-relaxed text-muted-foreground">{c.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="employers" aria-labelledby="employers-title" className="bg-primary text-primary-foreground">
          <div className="page-width grid gap-12 py-24 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:items-center">
            <div>
              <p className="font-mono text-[11px] tracking-[0.16em] uppercase opacity-75">For employers · The Pass</p>
              <h2 id="employers-title" className="mt-3 text-5xl leading-tight text-balance">Good hiring starts with a clear recipe.</h2>
              <p className="mt-5 max-w-md leading-relaxed opacity-85">
                Explore a sample shortlist with the context behind each suggestion. Review the requirements, ask a question, and choose who you would like to meet.
              </p>
              <ProvenanceLegend className="mt-6 text-primary-foreground/80 [&_dt]:text-primary-foreground" />
              <Button variant="secondary" size="lg" className="mt-8" asChild><Link href="/employer/pass">Open the demo pass<ArrowRight data-icon="inline-end" /></Link></Button>
            </div>
            <div className="text-foreground" aria-hidden="true">
              <div className="rail" />
              <div className="-mt-1 flex justify-center gap-5 overflow-hidden px-2">
                <SampleTicket name="Maya Chen" title="Product Designer" stamp="Ready" className="-rotate-1" />
                <SampleTicket name="Daniel Okafor" title="Senior Designer" stamp="To verify" className="hidden rotate-1 sm:block" />
              </div>
            </div>
          </div>
        </section>

        <section id="candidates" aria-labelledby="candidates-title" className="page-width grid gap-12 py-24 md:grid-cols-2">
          <div>
            <p className="eyebrow">For candidates · Today&apos;s Menu</p>
            <h2 id="candidates-title" className="mt-3 text-5xl leading-tight text-balance">A short menu, chosen for you.</h2>
          </div>
          <div className="flex flex-col gap-5">
            <p className="text-lg leading-relaxed text-pretty">
              Start with your goals, work preferences, and non-negotiables. Explore a handful of sample roles with the reasons written out, then decide what deserves your attention.
            </p>
            <ul className="flex flex-col border-t">
              {['Set your preferences before you explore', 'Keep a limit on how many opportunities you consider at once', 'An introduction needs both sides to say yes'].map((t) => (
                <li key={t} className="flex gap-3 border-b py-3 text-sm"><span className="mt-1.5 text-primary"><ProvenanceGlyph status="confirmed" /></span>{t}</li>
              ))}
            </ul>
            <Button size="lg" className="self-start" asChild><Link href="/candidate/opportunities">Preview Today&apos;s Menu<ArrowRight data-icon="inline-end" /></Link></Button>
          </div>
        </section>

        <section aria-labelledby="chef-help-title" className="page-width pb-20">
          <div className="flex flex-wrap items-center justify-between gap-6 rounded-md border bg-secondary px-6 py-7 md:px-8">
            <div className="flex max-w-xl items-start gap-4">
              <MessageCircle aria-hidden="true" className="mt-1 size-6 shrink-0 text-primary" strokeWidth={1.5} />
              <div>
                <h2 id="chef-help-title" className="text-2xl">A little help from the kitchen.</h2>
                <p className="mt-1 text-sm text-muted-foreground">Career Chef can explain the steps and help you find your way. Open the chat in the corner whenever you need a hand.</p>
              </div>
            </div>
            <Button variant="outline" asChild><Link href="/career-chef">Meet Career Chef<ArrowRight aria-hidden="true" /></Link></Button>
          </div>
        </section>
      </main>

      <footer className="double-rule">
        <div className="page-width flex flex-wrap items-center justify-between gap-4 py-8 pb-28 text-sm text-muted-foreground sm:pb-8">
          <Brand />
          <p>Demo build. All people, companies, and interactions shown are sample data.</p>
        </div>
      </footer>
    </>
  )
}
