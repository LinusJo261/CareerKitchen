'use client'
import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ArrowRight, Building2, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Brand } from '@/components/brand'
import { Progression } from '@/components/workspace/kit'
import { useDemo } from '@/lib/demo/adapter'
import type { Role } from '@/lib/contracts'
import { cn } from '@/lib/utils'

function EntryFrame({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh flex-col">
      <header className="page-width flex min-h-20 flex-wrap items-center justify-between gap-3 py-4"><Brand /><Badge variant="outline">Interactive demo</Badge></header>
      <div className="flex flex-1 items-center justify-center px-6 pt-10 pb-28 sm:pb-16">{children}</div>
    </main>
  )
}

function RolePicker({ value, onChange }: { value: Role; onChange: (r: Role) => void }) {
  const options = [
    { id: 'candidate' as const, label: 'I’m looking for a role', icon: UserRound },
    { id: 'employer' as const, label: 'I’m hiring', icon: Building2 },
  ]
  return (
    <fieldset>
      <legend className="mb-3 text-sm font-medium">Choose your workspace</legend>
      <div className="grid grid-cols-2 gap-3">
        {options.map(({ id, label, icon: Icon }) => (
          <label key={id} className="cursor-pointer">
            <input type="radio" name="workspace-role" value={id} checked={value === id} onChange={() => onChange(id)} className="peer sr-only" />
            <span className={cn('flex h-full flex-col items-start gap-3 rounded-md border p-4 text-left text-sm transition-colors hover:bg-muted peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring', value === id && 'border-primary bg-secondary')}>
              <Icon aria-hidden="true" className={cn('size-5', value === id ? 'text-primary' : 'text-muted-foreground')} />{label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export function AuthForm({ mode }: { mode: 'sign-in' | 'get-started' }) {
  const router = useRouter()
  const [role, setRole] = useState<Role>('candidate')
  const signUp = mode === 'get-started'

  function submit(e: React.FormEvent) {
    e.preventDefault()
    router.push(signUp && role === 'candidate' ? '/onboarding/candidate' : `/${role}`)
  }

  return (
    <EntryFrame>
      <form onSubmit={submit} className="rise flex w-full max-w-md flex-col gap-7" aria-describedby="demo-entry-note">
        <div>
          <p className="eyebrow mb-3">Your place at the table</p>
          <h1 className="text-4xl font-normal text-balance">{signUp ? 'Begin with what matters to you.' : 'Welcome back to the kitchen.'}</h1>
          <p className="mt-3 text-muted-foreground">{signUp ? 'Try a more thoughtful way to find your next role or teammate.' : 'Choose a workspace to explore the experience.'}</p>
        </div>
        <Alert><AlertDescription id="demo-entry-note">This is an interactive preview with fictional sample data. No account or password is needed.</AlertDescription></Alert>
        <RolePicker value={role} onChange={setRole} />
        <Button type="submit" size="lg">{signUp && role === 'candidate' ? 'Set up a candidate preview' : `Open the ${role} demo`}<ArrowRight aria-hidden="true" data-icon="inline-end" /></Button>
        <p className="text-center text-sm text-muted-foreground">{signUp ? 'Want to explore first? ' : 'Want to try candidate setup? '}<Link className="text-primary underline-offset-4 hover:underline" href={signUp ? '/sign-in' : '/get-started'}>{signUp ? 'Skip to a demo workspace' : 'Start the preview'}</Link></p>
      </form>
    </EntryFrame>
  )
}

const STEPS = ['Role', 'Must-haves', 'Capacity'] as const

export function CandidateOnboarding() {
  const router = useRouter()
  const { data, update } = useDemo()
  const [step, setStep] = useState(0)
  const [title, setTitle] = useState(data.profile.title)
  const [remote, setRemote] = useState(data.profile.remote)
  const [compensation, setCompensation] = useState(data.profile.compensation)
  const [capacity, setCapacity] = useState(String(data.profile.capacity))
  const [saving, setSaving] = useState(false)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const previousStep = useRef(step)
  const titleError = step === 0 && !title.trim()

  useEffect(() => {
    if (step !== previousStep.current) headingRef.current?.focus()
    previousStep.current = step
  }, [step])

  async function next(e: React.FormEvent) {
    e.preventDefault()
    if (titleError || saving) return
    if (step < STEPS.length - 1) return setStep(step + 1)
    setSaving(true)
    try {
      const ok = await update((s) => ({ ...s, profile: { ...s.profile, title: title.trim(), remote, compensation: compensation.trim(), capacity: Number(capacity) } }), 'Demo preferences saved. Your workspace is ready.')
      if (ok) router.push('/candidate')
    } finally {
      setSaving(false)
    }
  }

  return (
    <EntryFrame>
      <form onSubmit={next} className="rise flex w-full max-w-lg flex-col gap-7" aria-busy={saving}>
        <Progression steps={STEPS} current={step} />
        <p className="eyebrow" aria-live="polite">Step {step + 1} of {STEPS.length} · {STEPS[step]}</p>
        {step === 0 && <section className="flex flex-col gap-6"><h1 ref={headingRef} tabIndex={-1} className="text-3xl font-normal text-balance">What would you like to do next?</h1><p className="-mt-3 text-sm text-muted-foreground">We’ve filled in a fictional profile so you can try the setup. Changes last for this preview and reset when you refresh.</p><Field data-invalid={!title.trim()}><FieldLabel htmlFor="title">Role you’re looking for</FieldLabel><Input id="title" value={title} maxLength={120} aria-invalid={!title.trim()} aria-describedby={titleError ? 'title-error' : undefined} onChange={(e) => setTitle(e.target.value)} />{titleError && <FieldError id="title-error">Tell us the kind of role you want.</FieldError>}</Field></section>}
        {step === 1 && <section className="flex flex-col gap-6"><h1 ref={headingRef} tabIndex={-1} className="text-3xl font-normal text-balance">Your non-negotiables.</h1><p className="-mt-3 text-muted-foreground">Set the preferences you would want considered when exploring a role.</p>
          <FieldGroup>
            <Field><FieldLabel>Work arrangement</FieldLabel><ToggleGroup type="single" variant="outline" className="flex-wrap" value={remote} onValueChange={(v) => v && setRemote(v)} aria-label="Work arrangement">{['Remote', 'Remote or hybrid', 'On-site'].map((v) => <ToggleGroupItem key={v} value={v}>{v}</ToggleGroupItem>)}</ToggleGroup></Field>
            <Field><FieldLabel htmlFor="comp">Compensation expectation <span className="font-normal text-muted-foreground">(optional)</span></FieldLabel><Input id="comp" value={compensation} maxLength={120} aria-describedby="comp-hint" onChange={(e) => setCompensation(e.target.value)} /><FieldDescription id="comp-hint">Include a currency and range, for example $140,000–$175,000 USD / year.</FieldDescription></Field>
          </FieldGroup></section>}
        {step === 2 && <section className="flex flex-col gap-6"><h1 ref={headingRef} tabIndex={-1} className="text-3xl font-normal text-balance">How many decisions at once?</h1><p className="-mt-3 text-muted-foreground">Choose how many active opportunities you want to consider at a time, up to ten. You can change this later in your profile.</p>
          <ToggleGroup type="single" variant="outline" className="flex-wrap" value={capacity} onValueChange={(v) => v && setCapacity(v)} aria-label="Active decision capacity">{Array.from({ length: 10 }, (_, i) => String(i + 1)).map((n) => <ToggleGroupItem key={n} value={n} aria-label={`${n} active ${n === '1' ? 'opportunity' : 'opportunities'}`} className="w-10">{n}</ToggleGroupItem>)}</ToggleGroup><p className="text-sm font-medium text-primary">Your limit: {capacity} active {capacity === '1' ? 'opportunity' : 'opportunities'}</p></section>}
        <div className="flex justify-between gap-3">
          <Button type="button" variant="ghost" disabled={step === 0 || saving} onClick={() => setStep(step - 1)}><ArrowLeft aria-hidden="true" data-icon="inline-start" />Back</Button>
          <Button type="submit" disabled={titleError || saving}>{saving ? 'Saving…' : step === STEPS.length - 1 ? 'Open workspace' : 'Continue'}<ArrowRight aria-hidden="true" data-icon="inline-end" /></Button>
        </div>
      </form>
    </EntryFrame>
  )
}
