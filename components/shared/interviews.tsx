'use client'

import { useState } from 'react'
import { CalendarDays, CalendarPlus, Clock3 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { EmptyNote, PageHeader } from '@/components/workspace/kit'
import { useWorkspace } from '@/lib/workspace'
import type { Role } from '@/lib/contracts'

function slotLabel(start: string, end: string) {
  return `${new Date(start).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })} – ${new Date(end).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
}

export function InterviewsPage({ role }: { role: Role }) {
  const { data, execute } = useWorkspace()
  const [pending, setPending] = useState<string | null>(null)
  const interviews = data.interviews
    .filter((i) => i.side === role)
    .toSorted((a, b) =>
      (a.startAt ?? a.date).localeCompare(b.startAt ?? b.date),
    )

  async function confirm(
    id: string,
    matchId: string,
    slot: number,
    version: number,
  ) {
    if (pending) return
    setPending(id)
    try {
      await execute(
        'interview.confirm',
        { matchId, id, slot_index: slot, expected_version: version },
        'Interview confirmed.',
      )
    } finally {
      setPending(null)
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Your calendar"
        title="Interviews"
        description="Propose a choice of times for a mutual match. The other participant confirms the time."
        actions={<ScheduleDialog />}
      />
      {interviews.length === 0 ? (
        <EmptyNote
          icon={CalendarDays}
          title="No interview times yet"
          description="Propose times for a mutual match, or wait for the other participant to send options."
        />
      ) : (
        <ul className="panel divide-y">
          {interviews.map((interview) => {
            const date = new Date(
              interview.startAt ?? `${interview.date}T12:00:00`,
            )
            const proposed = interview.proposalStatus === 'PROPOSED'
            const canConfirm =
              proposed &&
              !!interview.matchId &&
              interview.version !== undefined &&
              interview.canConfirm === true
            return (
              <li
                key={interview.id}
                className="flex flex-wrap items-start gap-5 p-5 md:p-6"
              >
                <div className="flex size-14 flex-col items-center justify-center rounded-lg bg-accent text-accent-foreground">
                  <span className="text-[10px] font-medium uppercase">
                    {date.toLocaleString([], { month: 'short' })}
                  </span>
                  <span className="text-xl font-medium">{date.getDate()}</span>
                </div>
                <div className="min-w-48 flex-1">
                  <p className="font-medium">
                    {role === 'candidate'
                      ? `${interview.role} · ${interview.company}`
                      : `${interview.person} · ${interview.role}`}
                  </p>
                  <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Clock3 className="size-3.5" />
                    {interview.startAt
                      ? date.toLocaleString([], {
                          dateStyle: 'medium',
                          timeStyle: 'short',
                        })
                      : interview.time}
                  </p>
                  {proposed && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {canConfirm
                        ? 'Choose a time below. Times are shown in your current timezone.'
                        : 'Waiting for the other participant to choose a time.'}{' '}
                      Proposal timezone: {interview.timezoneLabel}.
                    </p>
                  )}
                  {proposed && (
                    <div className="mt-3 flex flex-col items-start gap-2">
                      {interview.slots?.map((slot, index) => (
                        <div
                          key={slot.start_at}
                          className="flex flex-wrap items-center gap-3 text-sm"
                        >
                          <span>{slotLabel(slot.start_at, slot.end_at)}</span>
                          {canConfirm && (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={
                                pending !== null ||
                                new Date(slot.start_at) <= new Date()
                              }
                              onClick={() =>
                                confirm(
                                  interview.proposalId ?? interview.id,
                                  interview.matchId!,
                                  index,
                                  interview.version!,
                                )
                              }
                            >
                              Confirm this time
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <Badge variant={proposed ? 'outline' : 'secondary'}>
                  {proposed ? 'Awaiting confirmation' : interview.status}
                </Badge>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}

function ScheduleDialog() {
  const { data, execute } = useWorkspace()
  const eligible = data.matches.filter(
    (match) =>
      match.status === 'ACTIVE' &&
      ['Mutual interest', 'Interviewing'].includes(match.stage) &&
      !match.state?.startsWith('CLOSED'),
  )
  const [open, setOpen] = useState(false)
  const [matchId, setMatchId] = useState('')
  const [times, setTimes] = useState(['', ''])
  const [duration, setDuration] = useState('30')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (pending) return
    const match = eligible.find((entry) => entry.id === matchId)
    const starts = times.map((value) => new Date(value))
    const minutes = Number(duration)
    if (
      !match ||
      starts.some(
        (date) => !Number.isFinite(date.getTime()) || date <= new Date(),
      ) ||
      starts[0].getTime() === starts[1].getTime() ||
      minutes < 15 ||
      minutes > 240
    ) {
      setError(
        'Choose a mutual match and two different future times, with a duration between 15 minutes and 4 hours.',
      )
      return
    }
    setError('')
    setPending(true)
    try {
      const ok = await execute(
        'interview.propose',
        {
          matchId: match.id,
          expected_version: match.version,
          timezone_label: timezone,
          slots: starts.map((start) => ({
            start_at: start.toISOString(),
            end_at: new Date(start.getTime() + minutes * 60_000).toISOString(),
          })),
        },
        'Interview times proposed. The other participant can confirm a time.',
      )
      if (ok) {
        setOpen(false)
        setTimes(['', ''])
        setMatchId('')
      }
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !pending && setOpen(value)}>
      <DialogTrigger asChild>
        <Button disabled={eligible.length === 0}>
          <CalendarPlus data-icon="inline-start" />
          Propose interview times
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="flex flex-col gap-6">
          <DialogHeader>
            <DialogTitle>Propose interview times</DialogTitle>
            <DialogDescription>
              Choose two options in {timezone}. The other participant must
              confirm. Calendar invitations are not sent automatically.
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="interview-match">Mutual match</FieldLabel>
              <Select
                value={matchId}
                onValueChange={setMatchId}
                disabled={pending}
              >
                <SelectTrigger id="interview-match">
                  <SelectValue placeholder="Choose a mutual match" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {eligible.map((match) => (
                      <SelectItem key={match.id} value={match.id}>
                        {match.name} · {match.role}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            {times.map((value, index) => (
              <Field key={index}>
                <FieldLabel htmlFor={`interview-time-${index}`}>
                  Option {index + 1}
                </FieldLabel>
                <Input
                  id={`interview-time-${index}`}
                  type="datetime-local"
                  required
                  value={value}
                  disabled={pending}
                  onChange={(event) =>
                    setTimes((current) =>
                      current.map((time, position) =>
                        position === index ? event.target.value : time,
                      ),
                    )
                  }
                />
              </Field>
            ))}
            <Field>
              <FieldLabel htmlFor="interview-duration">
                Duration in minutes
              </FieldLabel>
              <Input
                id="interview-duration"
                type="number"
                min={15}
                max={240}
                required
                value={duration}
                disabled={pending}
                onChange={(event) => setDuration(event.target.value)}
              />
            </Field>
            {error && <FieldError role="alert">{error}</FieldError>}
          </FieldGroup>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? 'Saving…' : 'Propose times'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
