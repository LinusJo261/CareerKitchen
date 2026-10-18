'use client'
import { useState } from 'react'
import { BadgeCheck, BriefcaseBusiness, Check, FileText, Plus, ShieldCheck, ShieldOff, Sparkles, UserPlus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { EmptyNote, Initials, PageHeader, Progression, SectionTitle } from '@/components/workspace/kit'
import { useDemo } from '@/lib/demo/adapter'
import type { PipelineStage, TeamMember, Vacancy } from '@/lib/contracts'
import { cn } from '@/lib/utils'

const PIPELINE: PipelineStage[] = ['Introduced', 'Mutual interest', 'Interviewing', 'Offer', 'Employment confirmed']

export function VacanciesPage({ openNew = false }: { openNew?: boolean }) {
  const { data, update } = useDemo()
  const [filter, setFilter] = useState<'All' | Vacancy['status']>('All')
  const list = data.vacancies.filter((v) => filter === 'All' || v.status === filter)
  const setStatus = (id: string, status: Vacancy['status']) => update((s) => ({ ...s, vacancies: s.vacancies.map((v) => v.id === id ? { ...v, status } : v) }), status === 'Active' ? 'Vacancy published.' : 'Vacancy closed.')
  return (
    <>
      <PageHeader eyebrow={data.organization.name} title="Vacancies" description="Clear roles attract the right people. Active vacancies are eligible for introductions." actions={<VacancyDialog defaultOpen={openNew} />} />
      <ToggleGroup type="single" variant="outline" size="sm" value={filter} onValueChange={(v) => v && setFilter(v as typeof filter)} className="mb-5" aria-label="Filter vacancies">
        {(['All', 'Active', 'Draft', 'Closed'] as const).map((f) => <ToggleGroupItem key={f} value={f}>{f}</ToggleGroupItem>)}
      </ToggleGroup>
      {list.length === 0 ? <EmptyNote icon={BriefcaseBusiness} title="No vacancies here" description="Try another filter, or create a new vacancy." /> : (
        <ul className="grid gap-4 lg:grid-cols-2">
          {list.map((v) => {
            const people = data.pipeline.filter((p) => p.vacancy === v.title).length
            return (
              <li key={v.id} className="panel flex flex-col gap-4 p-6">
                <div className="flex items-start justify-between gap-3"><div><p className="text-lg font-medium">{v.title}</p><p className="text-sm text-muted-foreground">{v.location} · {v.arrangement} · {v.employmentType}</p></div><Badge variant={v.status === 'Active' ? 'secondary' : 'outline'}>{v.status}</Badge></div>
                <p className="text-sm text-pretty text-muted-foreground">{v.summary}</p>
                <div className="flex flex-wrap gap-2">{v.skills.map((s) => <Badge key={s} variant="outline">{s}</Badge>)}</div>
                <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t pt-4 text-sm">
                  <span className="text-muted-foreground">{v.salary} · {people} in pipeline</span>
                  {v.status === 'Active' ? <Button size="sm" variant="ghost" onClick={() => setStatus(v.id, 'Closed')}>Close</Button> : <Button size="sm" onClick={() => setStatus(v.id, 'Active')}>Publish</Button>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}

function VacancyDialog({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const { update } = useDemo()
  const [open, setOpen] = useState(defaultOpen)
  const [submitted, setSubmitted] = useState(false)
  const [f, setF] = useState({ title: '', salary: '', location: '', arrangement: 'Hybrid', skills: '', summary: '' })
  const errors = { title: !f.title.trim(), salary: !f.salary.trim(), summary: f.summary.trim().length < 20 }
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setSubmitted(true)
    if (Object.values(errors).some(Boolean)) return
    const ok = await update((s) => ({ ...s, vacancies: [{ id: crypto.randomUUID(), title: f.title.trim(), company: s.organization.name, salary: f.salary.trim(), location: f.location.trim() || 'Not specified', arrangement: f.arrangement, skills: f.skills.split(',').map((x) => x.trim()).filter(Boolean), summary: f.summary.trim(), deadline: 'Not set', verified: s.organization.verified, employerInterested: false, status: 'Draft', employmentType: 'Full-time' }, ...s.vacancies] }), 'Draft vacancy created.')
    if (ok) { setOpen(false); setSubmitted(false); setF({ title: '', salary: '', location: '', arrangement: 'Hybrid', skills: '', summary: '' }) }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button><Plus data-icon="inline-start" />New vacancy</Button></DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="flex flex-col gap-6">
          <DialogHeader><DialogTitle>Create a vacancy</DialogTitle><DialogDescription>Saved as a draft. Publish when you’re ready.</DialogDescription></DialogHeader>
          <FieldGroup>
            <Field data-invalid={submitted && errors.title}><FieldLabel htmlFor="v-title">Role title</FieldLabel><Input id="v-title" value={f.title} aria-invalid={submitted && errors.title} onChange={(e) => setF({ ...f, title: e.target.value })} />{submitted && errors.title && <FieldError>Add a role title.</FieldError>}</Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field data-invalid={submitted && errors.salary}><FieldLabel htmlFor="v-salary">Compensation range</FieldLabel><Input id="v-salary" placeholder="$140,000 – $170,000" value={f.salary} aria-invalid={submitted && errors.salary} onChange={(e) => setF({ ...f, salary: e.target.value })} />{submitted && errors.salary && <FieldError>Ranges are required.</FieldError>}</Field>
              <Field><FieldLabel htmlFor="v-location">Location</FieldLabel><Input id="v-location" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
            </div>
            <Field><FieldLabel htmlFor="v-arr">Arrangement</FieldLabel>
              <Select value={f.arrangement} onValueChange={(v) => setF({ ...f, arrangement: v })}><SelectTrigger id="v-arr"><SelectValue /></SelectTrigger><SelectContent><SelectGroup>{['Remote', 'Hybrid', 'On-site'].map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectGroup></SelectContent></Select>
            </Field>
            <Field><FieldLabel htmlFor="v-skills">Skills</FieldLabel><Input id="v-skills" placeholder="Comma separated" value={f.skills} onChange={(e) => setF({ ...f, skills: e.target.value })} /></Field>
            <Field data-invalid={submitted && errors.summary}><FieldLabel htmlFor="v-summary">Summary</FieldLabel><Textarea id="v-summary" rows={3} value={f.summary} aria-invalid={submitted && errors.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} />{submitted && errors.summary ? <FieldError>Write at least 20 characters.</FieldError> : <FieldDescription>What makes this role worth someone’s next chapter?</FieldDescription>}</Field>
          </FieldGroup>
          <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit">Save draft</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function PipelinePage() {
  const { data, update } = useDemo()
  const [vacancy, setVacancy] = useState('All')
  const entries = data.pipeline.filter((p) => vacancy === 'All' || p.vacancy === vacancy)
  const advance = (id: string) => update((s) => ({ ...s, pipeline: s.pipeline.map((p) => {
    if (p.id !== id) return p
    const next = PIPELINE[PIPELINE.indexOf(p.stage) + 1]
    return next ? { ...p, stage: next, interest: 'Mutual', updated: 'Just now' } : p
  }) }), 'Stage updated.')
  return (
    <>
      <PageHeader eyebrow="Hiring progress" title="Pipeline" description="Candidates move forward only after mutual interest. Nobody advances on one side’s decision alone." actions={
        <Select value={vacancy} onValueChange={setVacancy}><SelectTrigger className="w-60" aria-label="Filter by vacancy"><SelectValue /></SelectTrigger><SelectContent><SelectGroup><SelectItem value="All">All vacancies</SelectItem>{[...new Set(data.pipeline.map((p) => p.vacancy))].map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectGroup></SelectContent></Select>
      } />
      <div className="-mx-1 flex gap-4 overflow-x-auto px-1 pb-4">
        {PIPELINE.map((stage) => {
          const col = entries.filter((p) => p.stage === stage)
          return (
            <section key={stage} className="flex w-72 shrink-0 flex-col gap-3" aria-label={stage}>
              <header className="flex items-center justify-between px-1"><h2 className="text-sm font-medium tracking-normal">{stage}</h2><span className="text-xs text-muted-foreground">{col.length}</span></header>
              <div className="flex min-h-40 flex-col gap-3 rounded-xl bg-muted/60 p-3">
                {col.length === 0 && <p className="p-4 text-center text-xs text-muted-foreground">No one here yet</p>}
                {col.map((p) => {
                  const canAdvance = stage !== 'Employment confirmed' && !(stage === 'Introduced' && p.interest !== 'Mutual')
                  return (
                    <article key={p.id} className="panel flex flex-col gap-3 p-4">
                      <div className="flex items-center gap-3"><Initials name={p.name} className="size-8 text-xs" /><div className="min-w-0"><p className="truncate text-sm font-medium">{p.name}</p><p className="truncate text-xs text-muted-foreground">{p.vacancy}</p></div></div>
                      <div className="flex flex-wrap gap-1.5">{p.skills.map((s) => <Badge key={s} variant="outline" className="text-[11px]">{s}</Badge>)}</div>
                      <div className="flex items-center justify-between text-xs text-muted-foreground"><span className="flex items-center gap-1"><BadgeCheck className="size-3.5 text-primary" />{p.verifiedEvidence} verified</span><span>{p.updated}</span></div>
                      {stage === 'Introduced' && p.interest !== 'Mutual' && <p className={cn('rounded-md px-2 py-1.5 text-xs', p.interest === 'Awaiting you' ? 'bg-orange/15 text-foreground' : 'bg-muted text-muted-foreground')}>{p.interest === 'Awaiting you' ? 'Candidate is interested — your decision' : 'Awaiting the candidate’s decision'}</p>}
                      {stage === 'Introduced' && p.interest === 'Awaiting you' && <Button size="sm" onClick={() => advance(p.id)}>Share interest</Button>}
                      {canAdvance && <Button size="sm" variant="outline" onClick={() => advance(p.id)}>Move to {PIPELINE[PIPELINE.indexOf(stage) + 1]}</Button>}
                    </article>
                  )
                })}
              </div>
            </section>
          )
        })}
      </div>
    </>
  )
}

export function EmployerOffersPage() {
  const { data, update } = useDemo()
  const ready = data.pipeline.filter((p) => p.stage === 'Offer')
  const [salary, setSalary] = useState<Record<string, string>>({})
  const sent = data.offers
  return (
    <>
      <PageHeader eyebrow="Formal offers" title="Offers" description="An offer is a distinct, formal step — separate from mutual interest and from PACT terms." />
      <div className="flex max-w-3xl flex-col gap-10">
        <section>
          <SectionTitle title="Ready for an offer" />
          {ready.length === 0 ? <EmptyNote icon={FileText} title="No one at the offer stage" description="Move a candidate to Offer in the pipeline after interviews." /> : (
            <ul className="panel divide-y">
              {ready.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-4 p-5">
                  <Initials name={p.name} />
                  <div className="min-w-40 flex-1"><p className="font-medium">{p.name}</p><p className="text-sm text-muted-foreground">{p.vacancy}</p></div>
                  <Input className="w-44" aria-label={`Offer compensation for ${p.name}`} placeholder="$190,000 / year" value={salary[p.id] ?? ''} onChange={(e) => setSalary({ ...salary, [p.id]: e.target.value })} />
                  <Button disabled={!salary[p.id]?.trim()} onClick={() => update((s) => ({ ...s, pipeline: s.pipeline.map((x) => x.id === p.id ? { ...x, stage: 'Employment confirmed', updated: 'Just now' } : x) }), `Offer recorded for ${p.name}. Awaiting their response.`)}>Send offer</Button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <SectionTitle title="Recent offers" />
          <ul className="panel divide-y">
            {sent.map((o) => <li key={o.id} className="flex flex-wrap items-center gap-4 p-5"><div className="flex-1"><p className="font-medium">{o.role}</p><p className="text-sm text-muted-foreground">{o.salary} · Respond by {o.deadline}</p></div><Badge variant="outline">{o.status}</Badge></li>)}
          </ul>
        </section>
      </div>
    </>
  )
}

export function OrganizationPage() {
  const { data, update } = useDemo()
  const org = data.organization
  const [desc, setDesc] = useState(org.description)
  return (
    <>
      <PageHeader eyebrow="Your organization" title={org.name} description="How your organization appears to candidates." />
      <div className="grid max-w-5xl gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="flex flex-col gap-4">
          <FieldGroup>
            <Field><FieldLabel htmlFor="org-desc">Public description</FieldLabel><Textarea id="org-desc" rows={4} value={desc} onChange={(e) => setDesc(e.target.value)} /><FieldDescription>Shown on every introduction candidates receive.</FieldDescription></Field>
          </FieldGroup>
          <Button className="self-start" disabled={desc === org.description || !desc.trim()} onClick={() => update((s) => ({ ...s, organization: { ...s.organization, description: desc } }), 'Organization updated.')}>Save changes</Button>
        </section>
        <aside className="panel flex flex-col gap-4 p-5">
          <div className="flex items-center justify-between"><h2 className="text-sm font-medium tracking-normal">Verification</h2><Badge variant="secondary"><BadgeCheck data-icon="inline-start" />{org.verification}</Badge></div>
          <dl className="flex flex-col gap-3 text-sm"><div><dt className="text-xs text-muted-foreground">Verified domain</dt><dd>{org.domain}</dd></div><div><dt className="text-xs text-muted-foreground">Active vacancies</dt><dd>{data.vacancies.filter((v) => v.status === 'Active').length}</dd></div></dl>
          <p className="text-xs text-muted-foreground">Verification is issued by the backend and cannot be changed from this screen.</p>
        </aside>
      </div>
    </>
  )
}

export function PactPage() {
  const { data, update } = useDemo()
  const p = data.policy
  const [reqDraft, setReqDraft] = useState('')
  const editable = p.status === 'Draft'
  const steps = ['Terms', 'Evidence', 'Authority', 'Authorize']
  const current = p.status === 'Authorized' ? 4 : p.requirements.length && p.evidence.length ? 2 : 1
  const set = (patch: Partial<typeof p>, msg?: string) => update((s) => ({ ...s, policy: { ...s.policy, ...patch } }), msg)
  return (
    <>
      <PageHeader eyebrow="Agreement-first" title="PACT terms" description="Preauthorize the terms a matched candidate can review and confirm. A confirmed PACT is not an offer or a guarantee of employment." actions={<Badge variant={p.status === 'Authorized' ? 'secondary' : 'outline'}>{p.status} · {p.version}</Badge>} />
      <Progression steps={steps} current={current} className="mb-8 max-w-2xl" />
      <div className="grid max-w-5xl gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex flex-col gap-6">
          <section className="panel p-6">
            <SectionTitle title={p.role} description="Compensation and arrangement for this role version." />
            <FieldGroup>
              <Field><FieldLabel htmlFor="pact-comp">Compensation</FieldLabel><Input id="pact-comp" disabled={!editable} value={p.compensation} onChange={(e) => set({ compensation: e.target.value })} /></Field>
              <Field><FieldLabel htmlFor="pact-arr">Work arrangement</FieldLabel><Input id="pact-arr" disabled={!editable} value={p.arrangement} onChange={(e) => set({ arrangement: e.target.value })} /></Field>
            </FieldGroup>
          </section>
          <section className="panel p-6">
            <SectionTitle title="Essential requirements" description="Only list what is genuinely essential." />
            <ul className="mb-4 flex flex-col gap-2">{p.requirements.map((r) => <li key={r} className="flex items-center gap-3 rounded-lg bg-muted px-3 py-2 text-sm"><Check className="size-4 text-primary" /><span className="flex-1">{r}</span>{editable && <Button variant="ghost" size="icon-xs" aria-label={`Remove ${r}`} onClick={() => set({ requirements: p.requirements.filter((x) => x !== r) })}><X /></Button>}</li>)}</ul>
            {editable && <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (reqDraft.trim()) { set({ requirements: [...p.requirements, reqDraft.trim()] }); setReqDraft('') } }}><Input aria-label="Add requirement" placeholder="Add a requirement" value={reqDraft} onChange={(e) => setReqDraft(e.target.value)} /><Button type="submit" variant="outline">Add</Button></form>}
          </section>
          <section className="panel p-6">
            <SectionTitle title="Evidence & stages" />
            <dl className="grid gap-4 text-sm sm:grid-cols-2"><div><dt className="text-xs text-muted-foreground">Evidence requested</dt><dd className="mt-1">{p.evidence.join(', ')}</dd></div><div><dt className="text-xs text-muted-foreground">Hiring stages</dt><dd className="mt-1">{p.stages.join(' → ')}</dd></div><div className="sm:col-span-2"><dt className="text-xs text-muted-foreground">Decision authority</dt><dd className="mt-1">{p.authority}</dd></div><div className="sm:col-span-2"><dt className="text-xs text-muted-foreground">Revocation</dt><dd className="mt-1">{p.revocation}</dd></div></dl>
          </section>
        </div>
        <aside className="flex flex-col gap-4">
          <div className="panel flex flex-col gap-3 p-5">
            <p className="text-sm font-medium">Expires {p.expires}</p>
            <p className="text-sm text-muted-foreground">Candidate confirmation: <span className="text-foreground">{p.candidateConfirmed ? 'Confirmed' : 'Not yet'}</span></p>
            {p.status === 'Draft' && (
              <AlertDialog>
                <AlertDialogTrigger asChild><Button disabled={!p.requirements.length}><ShieldCheck data-icon="inline-start" />Authorize terms</Button></AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader><AlertDialogTitle>Authorize these terms?</AlertDialogTitle><AlertDialogDescription>Matched candidates will be able to review and confirm them. Authorizing does not make an offer.</AlertDialogDescription></AlertDialogHeader>
                  <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={() => set({ status: 'Authorized' }, 'PACT terms authorized.')}>Authorize</AlertDialogAction></AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
            {p.status === 'Authorized' && <Button variant="outline" onClick={() => set({ status: 'Revoked', candidateConfirmed: false }, 'Terms revoked.')}><ShieldOff data-icon="inline-start" />Revoke</Button>}
            {p.status === 'Revoked' && <Button variant="outline" onClick={() => set({ status: 'Draft', version: 'v1.1' }, 'New draft version created.')}>Start a new version</Button>}
          </div>
          <Alert><ShieldCheck /><AlertTitle>Not an offer</AlertTitle><AlertDescription>PACT confirms shared terms. Offers and employment remain separate, formal steps.</AlertDescription></Alert>
        </aside>
      </div>
    </>
  )
}

export function WitnessPage() {
  const { data, update } = useDemo()
  const pending = data.clarifications.filter((c) => c.status === 'Pending')
  const resolved = data.clarifications.filter((c) => c.status !== 'Pending')
  const resolve = (id: string, status: 'Approved' | 'Rejected') => update((s) => ({ ...s, clarifications: s.clarifications.map((c) => c.id === id ? { ...c, status } : c) }), status === 'Approved' ? 'Change approved and applied.' : 'Suggestion dismissed.')
  return (
    <>
      <PageHeader eyebrow="Hiring clarity" title="WITNESS" description="Places where your hiring conditions are unclear or inconsistent. Nothing changes until you approve it." />
      <div className="flex max-w-3xl flex-col gap-10">
        {pending.length === 0 ? <EmptyNote icon={Sparkles} title="Everything is clear" description="No unresolved conditions right now." /> : (
          <ul className="flex flex-col gap-4">
            {pending.map((c) => (
              <li key={c.id} className="panel flex flex-col gap-4 p-6">
                <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{c.kind}</Badge></div>
                <div><p className="text-lg font-medium">{c.title}</p><p className="mt-1 text-sm text-muted-foreground">{c.description}</p></div>
                <div className="rounded-lg bg-muted p-4 text-sm"><p className="font-medium">Why this matters</p><p className="mt-1 text-pretty text-muted-foreground">{c.why}</p></div>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
                  <p className="text-sm"><span className="text-muted-foreground">Proposed: </span>{c.action}</p>
                  <div className="flex gap-2"><Button size="sm" variant="ghost" onClick={() => resolve(c.id, 'Rejected')}>Dismiss</Button><Button size="sm" onClick={() => resolve(c.id, 'Approved')}>Approve change</Button></div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {resolved.length > 0 && (
          <section><SectionTitle title="Resolved" />
            <ul className="panel divide-y">{resolved.map((c) => <li key={c.id} className="flex items-center justify-between gap-4 p-4 text-sm"><span>{c.title}</span><Badge variant={c.status === 'Approved' ? 'secondary' : 'outline'}>{c.status}</Badge></li>)}</ul>
          </section>
        )}
      </div>
    </>
  )
}

const ROLES: TeamMember['role'][] = ['Owner', 'Hiring manager', 'Recruiter', 'Interviewer']
const PERMISSIONS: Record<TeamMember['role'], string> = {
  Owner: 'Everything, including billing, verification, and PACT authorization.',
  'Hiring manager': 'Approve introductions, interviews, and request offers.',
  Recruiter: 'Manage vacancies, the pipeline, and messages.',
  Interviewer: 'View assigned interviews and leave feedback.',
}

export function TeamPage() {
  const { data, update } = useDemo()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<TeamMember['role']>('Interviewer')
  const [error, setError] = useState('')
  async function invite(e: React.FormEvent) {
    e.preventDefault()
    const value = email.trim().toLowerCase()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return setError('Enter a valid email address.')
    if (data.team.some((m) => m.email === value)) return setError('This person is already on the team.')
    setError('')
    const ok = await update((s) => ({ ...s, team: [...s.team, { id: crypto.randomUUID(), name: value.split('@')[0], email: value, role }] }), `Invitation sent to ${value}.`)
    if (ok) setEmail('')
  }
  return (
    <>
      <PageHeader eyebrow={data.organization.name} title="Team & permissions" description="Decisions are made by the people authorized to make them." />
      <div className="grid max-w-5xl gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-6">
          <form onSubmit={invite} className="panel flex flex-col gap-4 p-5">
            <FieldGroup className="sm:flex-row sm:items-start">
              <Field data-invalid={!!error} className="flex-1"><FieldLabel htmlFor="invite">Invite by email</FieldLabel><Input id="invite" type="email" value={email} aria-invalid={!!error} onChange={(e) => setEmail(e.target.value)} placeholder="name@forma.example" />{error && <FieldError>{error}</FieldError>}</Field>
              <Field className="sm:w-48"><FieldLabel htmlFor="invite-role">Role</FieldLabel><Select value={role} onValueChange={(v) => setRole(v as TeamMember['role'])}><SelectTrigger id="invite-role"><SelectValue /></SelectTrigger><SelectContent><SelectGroup>{ROLES.filter((r) => r !== 'Owner').map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectGroup></SelectContent></Select></Field>
            </FieldGroup>
            <Button type="submit" className="self-start"><UserPlus data-icon="inline-start" />Send invitation</Button>
          </form>
          <ul className="panel divide-y">
            {data.team.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-4 p-4">
                <Initials name={m.name} className="size-9" />
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{m.name}</p><p className="truncate text-xs text-muted-foreground">{m.email}</p></div>
                {m.role === 'Owner' ? <Badge variant="secondary">Owner</Badge> : (
                  <Select value={m.role} onValueChange={(v) => update((s) => ({ ...s, team: s.team.map((x) => x.id === m.id ? { ...x, role: v as TeamMember['role'] } : x) }), 'Role updated.')}>
                    <SelectTrigger size="sm" className="w-40" aria-label={`Role for ${m.name}`}><SelectValue /></SelectTrigger>
                    <SelectContent><SelectGroup>{ROLES.filter((r) => r !== 'Owner').map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectGroup></SelectContent>
                  </Select>
                )}
              </li>
            ))}
          </ul>
        </div>
        <aside className="panel flex flex-col divide-y self-start">
          {ROLES.map((r) => <div key={r} className="p-4"><p className="text-sm font-medium">{r}</p><p className="mt-1 text-xs leading-relaxed text-muted-foreground">{PERMISSIONS[r]}</p></div>)}
        </aside>
      </div>
    </>
  )
}
