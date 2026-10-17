'use client'
import { useState } from 'react'
import { CalendarDays, CalendarPlus, Clock3, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { EmptyNote, PageHeader } from '@/components/workspace/kit'
import { useDemo } from '@/lib/demo/adapter'
import type { Interview, Role } from '@/lib/contracts'

function formatDate(date: string) {
  const d = new Date(`${date}T12:00:00`)
  return { month: d.toLocaleString('en-US', { month: 'short' }), day: d.getDate(), weekday: d.toLocaleString('en-US', { weekday: 'long' }) }
}

export function InterviewsPage({ role }: { role: Role }) {
  const { data, update } = useDemo()
  const interviews = data.interviews.filter((i) => i.side === role).sort((a, b) => a.date.localeCompare(b.date))
  const setStatus = (id: string, status: Interview['status'], msg: string) => update((s) => ({ ...s, interviews: s.interviews.map((i) => i.id === id ? { ...i, status } : i) }), msg)

  return (
    <>
      <PageHeader eyebrow="Your calendar" title="Interviews" description={role === 'candidate' ? 'Conversations you’ve agreed to, in one calm place.' : 'Scheduled conversations with mutually matched candidates.'} actions={role === 'employer' && <ScheduleDialog />} />
      {interviews.length === 0 ? <EmptyNote icon={CalendarDays} title="Nothing scheduled" description="Interviews appear here once both sides agree on a time." /> : (
        <ul className="panel divide-y">
          {interviews.map((i) => {
            const d = formatDate(i.date)
            return (
              <li key={i.id} className="flex flex-wrap items-center gap-5 p-5 md:p-6">
                <div className="flex size-14 flex-col items-center justify-center rounded-lg bg-accent text-accent-foreground"><span className="text-[10px] font-medium uppercase">{d.month}</span><span className="text-xl font-medium">{d.day}</span></div>
                <div className="min-w-48 flex-1">
                  <p className="font-medium">{role === 'candidate' ? `${i.role} · ${i.company}` : `${i.person} · ${i.role}`}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground"><span className="flex items-center gap-1.5"><Clock3 className="size-3.5" />{d.weekday}, {i.time}</span><span className="flex items-center gap-1.5"><Video className="size-3.5" />{i.format}</span></p>
                </div>
                <Badge variant={i.status === 'Reschedule requested' ? 'outline' : 'secondary'}>{i.status}</Badge>
                <div className="flex gap-2">
                  {i.status !== 'Confirmed' && <Button size="sm" onClick={() => setStatus(i.id, 'Confirmed', 'Interview confirmed.')}>Confirm</Button>}
                  {i.status !== 'Reschedule requested' && <Button size="sm" variant="outline" onClick={() => setStatus(i.id, 'Reschedule requested', 'Reschedule requested. The other side will propose new times.')}>Request new time</Button>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}

function ScheduleDialog() {
  const { data, update } = useDemo()
  const eligible = data.pipeline.filter((p) => p.interest === 'Mutual')
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ person: '', date: '', time: '', format: 'Video · Portfolio interview' })
  const [submitted, setSubmitted] = useState(false)
  const valid = form.person && form.date && form.time

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setSubmitted(true)
    if (!valid) return
    const entry = eligible.find((p) => p.id === form.person)!
    const ok = await update((s) => ({
      ...s,
      interviews: [...s.interviews, { id: crypto.randomUUID(), side: 'employer', company: s.organization.name, role: entry.vacancy, person: entry.name, date: form.date, time: form.time, format: form.format, status: 'Scheduled' }],
      pipeline: s.pipeline.map((p) => p.id === entry.id && p.stage === 'Mutual interest' ? { ...p, stage: 'Interviewing', updated: 'Just now' } : p),
    }), `Invitation sent to ${entry.name}.`)
    if (ok) { setOpen(false); setSubmitted(false); setForm({ person: '', date: '', time: '', format: form.format }) }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button><CalendarPlus data-icon="inline-start" />Schedule interview</Button></DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="flex flex-col gap-6">
          <DialogHeader><DialogTitle>Schedule an interview</DialogTitle><DialogDescription>Only mutually matched candidates can be invited.</DialogDescription></DialogHeader>
          <FieldGroup>
            <Field data-invalid={submitted && !form.person}>
              <FieldLabel htmlFor="person">Candidate</FieldLabel>
              <Select value={form.person} onValueChange={(v) => setForm({ ...form, person: v })}>
                <SelectTrigger id="person" aria-invalid={submitted && !form.person}><SelectValue placeholder="Choose a mutual match" /></SelectTrigger>
                <SelectContent><SelectGroup>{eligible.map((p) => <SelectItem key={p.id} value={p.id}>{p.name} · {p.vacancy}</SelectItem>)}</SelectGroup></SelectContent>
              </Select>
              {submitted && !form.person && <FieldError>Choose a candidate.</FieldError>}
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field data-invalid={submitted && !form.date}><FieldLabel htmlFor="date">Date</FieldLabel><Input id="date" type="date" value={form.date} aria-invalid={submitted && !form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
              <Field data-invalid={submitted && !form.time}><FieldLabel htmlFor="time">Time</FieldLabel><Input id="time" placeholder="2:00 PM ET" value={form.time} aria-invalid={submitted && !form.time} onChange={(e) => setForm({ ...form, time: e.target.value })} /></Field>
            </div>
            <Field><FieldLabel htmlFor="format">Format</FieldLabel><Input id="format" value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value })} /></Field>
          </FieldGroup>
          <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit">Send invitation</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
