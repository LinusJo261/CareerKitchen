'use client'
import Link from 'next/link'
import { BookOpen } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyNote, PageHeader, SectionTitle } from '@/components/workspace/kit'
import { useDemo } from '@/lib/demo/adapter'
import { usePass } from '@/lib/demo/pass'
import type { Role } from '@/lib/contracts'

interface Entry { id: string; title: string; detail: string; tag: string }

function EntryList({ entries }: { entries: Entry[] }) {
  return (
    <ul className="panel divide-y">
      {entries.map((e) => (
        <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 p-5">
          <div className="min-w-0">
            <p className="text-sm font-medium">{e.title}</p>
            <p className="mt-1 text-xs text-muted-foreground">{e.detail}</p>
          </div>
          <Badge variant="outline">{e.tag}</Badge>
        </li>
      ))}
    </ul>
  )
}

function CandidateHistory() {
  const { data } = useDemo()
  const decisions: Entry[] = data.opportunities
    .filter((o) => data.decisions[o.id])
    .map((o) => ({ id: o.id, title: `${o.title} · ${o.company}`, detail: o.reason, tag: data.decisions[o.id] === 'interested' ? 'Interested' : 'Passed' }))
  const outcomes: Entry[] = [
    ...data.matches.map((m) => ({ id: m.id, title: `${m.role} · ${m.company}`, detail: `Updated ${m.updated.toLowerCase()}`, tag: m.stage })),
    ...data.offers.map((o) => ({ id: o.id, title: `Offer: ${o.role} · ${o.company}`, detail: `${o.salary} · Start ${o.start}`, tag: o.status })),
  ]
  return (
    <>
      <PageHeader eyebrow="Recipe Book" title="Your history" description="Every decision you’ve made, and where each introduction ended up." />
      <div className="flex flex-col gap-8">
        <section>
          <SectionTitle title="Your decisions" description="Opportunities you marked interested or passed on in this session." />
          {decisions.length ? <EntryList entries={decisions} /> : (
            <EmptyNote icon={BookOpen} title="No decisions yet" description="Decisions from Today’s Menu will be recorded here.">
              <Button asChild size="sm"><Link href="/candidate">Open Today’s Menu</Link></Button>
            </EmptyNote>
          )}
        </section>
        <section>
          <SectionTitle title="Introductions and offers" />
          {outcomes.length ? <EntryList entries={outcomes} /> : <EmptyNote icon={BookOpen} title="Nothing yet" description="Mutual matches and offers will appear here." />}
        </section>
      </div>
    </>
  )
}

function EmployerHistory() {
  const pass = usePass()
  const decided: Entry[] = Object.entries(pass.introductions).map(([id, d]) => {
    const c = pass.candidates.find((x) => x.id === id)
    return { id, title: c?.name ?? 'Candidate', detail: `${c?.title ?? ''} · ${pass.order.title}`, tag: d === 'Requested' ? 'Introduction requested' : 'Passed' }
  })
  return (
    <>
      <PageHeader eyebrow="Recipe Book" title="Order history" description={`Everything that happened on ticket ${pass.order.ticket}, ${pass.order.title}.`} />
      <div className="flex flex-col gap-8">
        <section>
          <SectionTitle title="Decisions" />
          {decided.length ? <EntryList entries={decided} /> : (
            <EmptyNote icon={BookOpen} title="No decisions yet" description="Request introductions or pass on candidates at The Pass.">
              <Button asChild size="sm"><Link href="/employer/pass">Go to The Pass</Link></Button>
            </EmptyNote>
          )}
        </section>
        <section>
          <SectionTitle title="Kitchen log" description="Recipe edits, taste tests, and decisions, newest first." />
          {pass.log.length ? (
            <ol className="panel divide-y">
              {pass.log.map((l) => (
                <li key={l.id} className="flex items-center justify-between gap-4 p-4 text-sm">
                  <span className="text-pretty">{l.text}</span>
                  <span className="shrink-0 font-mono text-xs text-muted-foreground">{l.time}</span>
                </li>
              ))}
            </ol>
          ) : <EmptyNote icon={BookOpen} title="The log is empty" description="Changes you make on The Pass are recorded here." />}
        </section>
      </div>
    </>
  )
}

export function RecipeBook({ role }: { role: Role }) {
  return role === 'employer' ? <EmployerHistory /> : <CandidateHistory />
}
