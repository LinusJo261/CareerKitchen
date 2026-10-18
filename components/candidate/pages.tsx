'use client'
import { useState } from 'react'
import Link from 'next/link'
import { BadgeCheck, CircleDashed, EyeOff, FileCheck2, FileText, HeartHandshake, MessageSquare, Plus, ShieldCheck, ShieldOff, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { CompanyMark } from '@/components/brand'
import { EmptyNote, PageHeader, Progression, SectionTitle } from '@/components/workspace/kit'
import { useDemo } from '@/lib/demo/adapter'
import type { RequirementWeight, Stage } from '@/lib/contracts'

const STAGES: Stage[] = ['Mutual interest', 'Interviewing', 'Offer', 'Employment confirmed']

export function MatchesPage() {
  const { data } = useDemo()
  const awaiting = data.opportunities.filter((o) => data.decisions[o.id] === 'interested')
  return (
    <>
      <PageHeader eyebrow="Mutual interest" title="My matches" description="Both sides said yes. Here’s where each conversation stands." />
      {data.matches.length === 0 ? <EmptyNote icon={HeartHandshake} title="No mutual matches yet" description="When an employer shares interest back, the match appears here." /> : (
        <ul className="flex flex-col gap-4">
          {data.matches.map((m) => (
            <li key={m.id} className="panel flex flex-col gap-5 p-5 md:p-6">
              <div className="flex flex-wrap items-center gap-4">
                <CompanyMark name={m.company} />
                <div className="flex-1"><p className="font-medium">{m.role}</p><p className="text-sm text-muted-foreground">{m.company} · Updated {m.updated.toLowerCase()}</p></div>
                <Button variant="outline" size="sm" asChild><Link href="/candidate/messages"><MessageSquare data-icon="inline-start" />Message</Link></Button>
                {m.stage === 'Offer' && <Button size="sm" asChild><Link href="/candidate/offers"><FileText data-icon="inline-start" />Review offer</Link></Button>}
              </div>
              <Progression steps={STAGES} current={m.stage === 'Employment confirmed' ? STAGES.length : STAGES.indexOf(m.stage)} />
            </li>
          ))}
        </ul>
      )}
      {awaiting.length > 0 && (
        <section className="mt-10">
          <SectionTitle title="Awaiting the employer" description="You shared interest. A match forms only if they share interest too." />
          <ul className="panel divide-y">
            {awaiting.map((o) => <li key={o.id} className="flex items-center gap-4 p-5"><CompanyMark name={o.company} className="size-9 text-base" /><span className="flex-1 text-sm"><span className="font-medium">{o.title}</span> · {o.company}</span><Badge variant="outline"><CircleDashed data-icon="inline-start" />Awaiting response</Badge></li>)}
          </ul>
        </section>
      )}
    </>
  )
}

export function CandidateOffersPage() {
  const { data, update } = useDemo()
  const respond = (id: string, status: 'Accepted' | 'Declined') => update((s) => ({ ...s, offers: s.offers.map((o) => o.id === id ? { ...o, status } : o) }), status === 'Accepted' ? 'Offer accepted. The employer will confirm your start.' : 'Offer declined. The employer has been notified.')
  const confirmStart = (company: string) => update((s) => ({ ...s, matches: s.matches.map((m) => m.company === company ? { ...m, stage: 'Employment confirmed', updated: 'Just now' } : m) }), 'Employment start confirmed. Congratulations.')
  return (
    <>
      <PageHeader eyebrow="Formal offers" title="Offers" description="Actual offers from employers. Take the time you need — nothing here is accepted until you say so." />
      {data.offers.length === 0 ? <EmptyNote icon={FileText} title="No offers yet" description="Offers appear here after interviews with mutually matched employers." /> : data.offers.map((o) => {
        const confirmed = data.matches.some((m) => m.company === o.company && m.stage === 'Employment confirmed')
        return (
          <article key={o.id} className="panel max-w-3xl overflow-hidden">
            <div className="flex flex-wrap items-center gap-4 border-b p-6">
              <CompanyMark name={o.company} />
              <div className="flex-1"><p className="text-lg font-medium">{o.role}</p><p className="text-sm text-muted-foreground">{o.company}</p></div>
              <Badge variant={o.status === 'Awaiting response' ? 'outline' : 'secondary'}>{confirmed ? 'Employment confirmed' : o.status}</Badge>
            </div>
            <dl className="grid gap-6 p-6 sm:grid-cols-3">
              {[['Compensation', o.salary], ['Proposed start', o.start], ['Respond by', o.deadline]].map(([k, v]) => <div key={k}><dt className="text-xs text-muted-foreground">{k}</dt><dd className="mt-1 font-medium">{v}</dd></div>)}
            </dl>
            <div className="flex flex-wrap items-center justify-end gap-2 border-t bg-muted/40 p-4">
              {o.status === 'Awaiting response' && <>
                <ConfirmButton variant="outline" label="Decline" title="Decline this offer?" description={`${o.company} will be notified. This can’t be undone in the demo.`} onConfirm={() => respond(o.id, 'Declined')} />
                <ConfirmButton label="Accept offer" title="Accept this offer?" description="Accepting is a formal response to this offer. Your start date is confirmed separately with the employer." onConfirm={() => respond(o.id, 'Accepted')} />
              </>}
              {o.status === 'Accepted' && !confirmed && <Button onClick={() => confirmStart(o.company)}><BadgeCheck data-icon="inline-start" />Confirm employment start</Button>}
              {(o.status === 'Declined' || confirmed) && <p className="text-sm text-muted-foreground">No further action needed.</p>}
            </div>
          </article>
        )
      })}
    </>
  )
}

function ConfirmButton({ label, title, description, onConfirm, variant = 'default' }: { label: string; title: string; description: string; onConfirm: () => void; variant?: 'default' | 'outline' }) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild><Button variant={variant}>{label}</Button></AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader><AlertDialogTitle>{title}</AlertDialogTitle><AlertDialogDescription>{description}</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={onConfirm}>{label}</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ProfilePage() {
  const { data, update } = useDemo()
  const p = data.profile
  const [summary, setSummary] = useState(p.summary)
  const [skill, setSkill] = useState('')
  const save = (patch: Partial<typeof p>, msg = 'Profile updated.') => update((s) => ({ ...s, profile: { ...s.profile, ...patch } }), msg)
  return (
    <>
      <PageHeader eyebrow="About you" title="Profile & skills" description="What employers see after you consent — and the priorities that shape your introductions." actions={<Button variant="outline" asChild><Link href="/onboarding/candidate">Redo onboarding</Link></Button>} />
      <div className="grid max-w-5xl gap-10 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-10">
          <section>
            <SectionTitle title="Summary" />
            <FieldGroup>
              <Field><FieldLabel htmlFor="summary">Professional summary</FieldLabel><Textarea id="summary" rows={4} value={summary} onChange={(e) => setSummary(e.target.value)} /><FieldDescription>{summary.length}/400 characters</FieldDescription></Field>
              <Button className="self-start" disabled={summary === p.summary || summary.length > 400 || !summary.trim()} onClick={() => save({ summary })}>Save summary</Button>
            </FieldGroup>
          </section>
          <section>
            <SectionTitle title="Skills" />
            <div className="mb-4 flex flex-wrap gap-2">{p.skills.map((s) => <Badge key={s} variant="secondary" className="gap-1 pr-1">{s}<button aria-label={`Remove ${s}`} className="rounded-full p-0.5 hover:bg-background" onClick={() => save({ skills: p.skills.filter((x) => x !== s) }, `Removed ${s}.`)}><X className="size-3" /></button></Badge>)}</div>
            <form className="flex max-w-sm gap-2" onSubmit={(e) => { e.preventDefault(); const v = skill.trim(); if (v && !p.skills.includes(v)) { save({ skills: [...p.skills, v] }, `Added ${v}.`); setSkill('') } }}>
              <Input aria-label="Add a skill" placeholder="Add a skill" value={skill} onChange={(e) => setSkill(e.target.value)} /><Button type="submit" variant="outline" size="icon" aria-label="Add skill"><Plus /></Button>
            </form>
          </section>
          <section>
            <SectionTitle title="Requirements & preferences" description="Must-haves are treated as non-negotiable when introductions are selected." />
            <div className="panel divide-y">
              {Object.entries(p.requirements ?? {}).map(([k, v]) => (
                <div key={k} className="flex flex-wrap items-center justify-between gap-3 p-4">
                  <span className="text-sm font-medium">{k}</span>
                  <ToggleGroup type="single" size="sm" variant="outline" value={v} onValueChange={(nv) => nv && save({ requirements: { ...p.requirements, [k]: nv as RequirementWeight } }, 'Priority saved.')} aria-label={`${k} priority`}>
                    {(['Must-have', 'Preference', 'Flexible'] as const).map((w) => <ToggleGroupItem key={w} value={w}>{w}</ToggleGroupItem>)}
                  </ToggleGroup>
                </div>
              ))}
            </div>
          </section>
        </div>
        <aside className="flex flex-col gap-5">
          <section className="panel p-5">
            <h2 className="text-sm font-medium tracking-normal">Active decision capacity</h2>
            <p className="mt-1 text-sm text-muted-foreground">How many opportunities can await your decision at once. As you decide, new ones can arrive.</p>
            <ToggleGroup type="single" variant="outline" size="sm" className="mt-4 flex-wrap" value={String(p.capacity)} onValueChange={(v) => v && save({ capacity: Number(v) }, `Capacity set to ${v} at a time.`)} aria-label="Active decision capacity">
              {Array.from({ length: 10 }, (_, i) => String(i + 1)).map((n) => <ToggleGroupItem key={n} value={n} className="w-9">{n}</ToggleGroupItem>)}
            </ToggleGroup>
          </section>
          <dl className="panel divide-y text-sm">
            {[['Location', p.location], ['Work arrangement', p.remote], ['Availability', p.availability], ['Experience', p.experience], ['Compensation expectation', `${p.compensation} · private`]].map(([k, v]) => <div key={k} className="flex flex-col gap-1 p-4"><dt className="text-xs text-muted-foreground">{k}</dt><dd>{v}</dd></div>)}
          </dl>
          <p className="flex gap-2 text-xs text-muted-foreground"><EyeOff className="size-3.5 shrink-0" />Your compensation floor is never shown to employers.</p>
        </aside>
      </div>
    </>
  )
}

export function EvidencePage() {
  const { data, update } = useDemo()
  const submit = (id: string) => update((s) => ({ ...s, evidence: s.evidence.map((e) => e.id === id ? { ...e, status: 'Pending', issuer: 'Demo request · pending verification' } : e) }), 'Demo verification request recorded. No documents were sent.')
  return (
    <>
      <PageHeader eyebrow="Your credentials" title="Qualification evidence" description="Explore sample evidence statuses and consent. Demo requests stay in this session." />
      <ul className="panel max-w-3xl divide-y">
        {data.evidence.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-4 p-5">
            <span className="flex size-10 items-center justify-center rounded-lg bg-secondary text-primary">{e.status === 'Verified' ? <BadgeCheck className="size-5" /> : <FileCheck2 className="size-5" />}</span>
            <div className="flex-1"><p className="font-medium">{e.name}</p><p className="text-sm text-muted-foreground">{e.issuer}</p></div>
            <Badge variant={e.status === 'Verified' ? 'secondary' : 'outline'}>{e.status}</Badge>
            {e.status === 'Not shared' && <Button size="sm" variant="outline" onClick={() => submit(e.id)}>Try verification request</Button>}
          </li>
        ))}
      </ul>
      <p className="mt-4 max-w-3xl text-xs text-muted-foreground">“Verified” labels are fictional sample records. This demo does not upload evidence or perform real verification.</p>
    </>
  )
}

export function PrivacyPage() {
  const { data, update } = useDemo()
  const setConsent = (id: string, granted: boolean) => update((s) => ({ ...s, consents: s.consents.map((c) => c.id === id ? { ...c, granted } : c) }), granted ? 'Consent granted.' : 'Consent revoked. The disclosure is no longer shared.')
  const pact = data.policy
  return (
    <>
      <PageHeader eyebrow="You’re in control" title="Privacy & consent" description="Every disclosure has a recipient, a purpose, and an expiry. Revoke anything, anytime." />
      <div className="flex max-w-3xl flex-col gap-10">
        <section>
          <SectionTitle title="Agreement requests" description="Terms an employer has preauthorized. Confirming is not an offer or employment guarantee." />
          {pact.status !== 'Authorized' ? <EmptyNote icon={ShieldCheck} title="No requests right now" description="When an employer authorizes terms for a role you’re matched with, you can review them here." /> : (
            <article className="panel p-6">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><p className="font-medium">{pact.role} · {pact.version} · {data.organization.name}</p><Badge variant={pact.candidateConfirmed ? 'secondary' : 'outline'}>{pact.candidateConfirmed ? 'You confirmed these terms' : 'Awaiting your review'}</Badge></div>
              <dl className="grid gap-4 text-sm sm:grid-cols-2">
                <div><dt className="text-xs text-muted-foreground">Compensation</dt><dd className="mt-1">{pact.compensation}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Arrangement</dt><dd className="mt-1">{pact.arrangement}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Evidence requested</dt><dd className="mt-1">{pact.evidence.join(', ')}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Expires</dt><dd className="mt-1">{pact.expires}</dd></div>
              </dl>
              <div className="mt-6 flex justify-end">
                <Button variant={pact.candidateConfirmed ? 'outline' : 'default'} onClick={() => update((s) => ({ ...s, policy: { ...s.policy, candidateConfirmed: !s.policy.candidateConfirmed } }), pact.candidateConfirmed ? 'Confirmation withdrawn.' : 'Terms confirmed. This is not an offer.')}>{pact.candidateConfirmed ? 'Withdraw confirmation' : 'Confirm these terms'}</Button>
              </div>
            </article>
          )}
        </section>
        <section>
          <SectionTitle title="Disclosures" />
          <ul className="flex flex-col gap-3">
            {data.consents.map((c) => (
              <li key={c.id} className="panel flex flex-col gap-4 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div><p className="font-medium">{c.label}</p><p className="mt-1 text-sm text-muted-foreground">Shared with <span className="text-foreground">{c.recipient}</span> · Expires {c.expires}</p></div>
                  <Badge variant={c.granted ? 'secondary' : 'outline'}>{c.granted ? 'Shared' : 'Not shared'}</Badge>
                </div>
                <p className="rounded-lg bg-muted p-3 text-sm"><span className="font-medium">Exact request: </span>{c.purpose}</p>
                <div className="flex justify-end">
                  {c.granted ? (
                    <AlertDialog>
                      <AlertDialogTrigger asChild><Button size="sm" variant="outline"><ShieldOff data-icon="inline-start" />Revoke</Button></AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader><AlertDialogTitle>Revoke this disclosure?</AlertDialogTitle><AlertDialogDescription>{c.recipient} will lose access to “{c.label}”. Steps that depend on it may pause.</AlertDialogDescription></AlertDialogHeader>
                        <AlertDialogFooter><AlertDialogCancel>Keep sharing</AlertDialogCancel><AlertDialogAction onClick={() => setConsent(c.id, false)}>Revoke</AlertDialogAction></AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  ) : <Button size="sm" onClick={() => setConsent(c.id, true)}><ShieldCheck data-icon="inline-start" />Grant</Button>}
                </div>
              </li>
            ))}
          </ul>
        </section>
        <Alert><EyeOff /><AlertTitle>Never shared without consent</AlertTitle><AlertDescription>Your compensation floor, current employer, and contact details stay private unless you explicitly share them.</AlertDescription></Alert>
      </div>
    </>
  )
}
