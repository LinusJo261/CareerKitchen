'use client'
import { useState } from 'react'
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
      <header className="page-width flex h-20 items-center justify-between"><Link href="/" aria-label="Career Kitchen home"><Brand /></Link><Badge variant="outline">Demo environment</Badge></header>
      <div className="flex flex-1 items-center justify-center px-6 py-10">{children}</div>
    </main>
  )
}

function RolePicker({ value, onChange }: { value: Role; onChange: (r: Role) => void }) {
  const options = [
    { id: 'candidate' as const, label: 'I’m looking for a role', icon: UserRound },
    { id: 'employer' as const, label: 'I’m hiring', icon: Building2 },
  ]
  return (
    <div role="radiogroup" aria-label="Workspace" className="grid grid-cols-2 gap-3">
      {options.map(({ id, label, icon: Icon }) => (
        <button key={id} type="button" role="radio" aria-checked={value === id} onClick={() => onChange(id)} className={cn('flex flex-col items-start gap-3 rounded-xl border p-4 text-left text-sm transition-colors hover:bg-muted', value === id && 'border-primary bg-secondary')}>
          <Icon className={cn('size-5', value === id ? 'text-primary' : 'text-muted-foreground')} />{label}
        </button>
      ))}
    </div>
  )
}

export function AuthForm({ mode }: { mode: 'sign-in' | 'get-started' }) {
  const router = useRouter()
  const [role, setRole] = useState<Role>('candidate')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const emailError = !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
  const passwordError = password.length < 8
  const signUp = mode === 'get-started'

  function submit(e: React.FormEvent) {
    e.preventDefault(); setSubmitted(true)
    if (emailError || passwordError) return
    router.push(signUp && role === 'candidate' ? '/onboarding/candidate' : `/${role}`)
  }

  return (
    <EntryFrame>
      <form onSubmit={submit} className="rise flex w-full max-w-md flex-col gap-8" noValidate>
        <div>
          <h1 className="text-3xl font-medium text-balance">{signUp ? 'Begin with what matters to you' : 'Welcome back'}</h1>
          <p className="mt-2 text-muted-foreground">{signUp ? 'A few thoughtful introductions, not a flood of listings.' : 'Sign in to continue where you left off.'}</p>
        </div>
        <RolePicker value={role} onChange={setRole} />
        <FieldGroup>
          <Field data-invalid={submitted && emailError}><FieldLabel htmlFor="email">Email</FieldLabel><Input id="email" type="email" autoComplete="email" value={email} aria-invalid={submitted && emailError} onChange={(e) => setEmail(e.target.value)} />{submitted && emailError && <FieldError>Enter a valid email address.</FieldError>}</Field>
          <Field data-invalid={submitted && passwordError}><FieldLabel htmlFor="password">Password</FieldLabel><Input id="password" type="password" autoComplete={signUp ? 'new-password' : 'current-password'} value={password} aria-invalid={submitted && passwordError} onChange={(e) => setPassword(e.target.value)} />{submitted && passwordError ? <FieldError>Use at least 8 characters.</FieldError> : signUp && <FieldDescription>At least 8 characters.</FieldDescription>}</Field>
        </FieldGroup>
        <Button type="submit" size="lg">{signUp ? 'Create account' : 'Sign in'}<ArrowRight data-icon="inline-end" /></Button>
        <Alert><AlertDescription>Demo only — no account is created and nothing is sent. Authentication is handled by the backend in production.</AlertDescription></Alert>
        <p className="text-center text-sm text-muted-foreground">{signUp ? 'Already have an account? ' : 'New to Career Kitchen? '}<Link className="text-primary underline-offset-4 hover:underline" href={signUp ? '/sign-in' : '/get-started'}>{signUp ? 'Sign in' : 'Get started'}</Link></p>
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
  const titleError = step === 0 && !title.trim()

  async function next() {
    if (titleError) return
    if (step < STEPS.length - 1) return setStep(step + 1)
    const ok = await update((s) => ({ ...s, profile: { ...s.profile, title: title.trim(), remote, compensation, capacity: Number(capacity) } }), 'You’re all set. Your first introductions are ready.')
    if (ok) router.push('/candidate')
  }

  return (
    <EntryFrame>
      <div className="rise flex w-full max-w-lg flex-col gap-8">
        <Progression steps={STEPS} current={step} />
        {step === 0 && <section className="flex flex-col gap-6"><h1 className="text-3xl font-medium text-balance">What would you like to do next?</h1><Field data-invalid={!title.trim()}><FieldLabel htmlFor="title">Role you’re looking for</FieldLabel><Input id="title" value={title} aria-invalid={!title.trim()} onChange={(e) => setTitle(e.target.value)} />{!title.trim() && <FieldError>Tell us the kind of role you want.</FieldError>}</Field></section>}
        {step === 1 && <section className="flex flex-col gap-6"><h1 className="text-3xl font-medium text-balance">Your non-negotiables</h1><p className="-mt-3 text-muted-foreground">We only introduce opportunities that respect these. Compensation stays private.</p>
          <FieldGroup>
            <Field><FieldLabel>Work arrangement</FieldLabel><ToggleGroup type="single" variant="outline" value={remote} onValueChange={(v) => v && setRemote(v)} aria-label="Work arrangement">{['Remote', 'Remote or hybrid', 'On-site'].map((v) => <ToggleGroupItem key={v} value={v}>{v}</ToggleGroupItem>)}</ToggleGroup></Field>
            <Field><FieldLabel htmlFor="comp">Compensation expectation</FieldLabel><Input id="comp" value={compensation} onChange={(e) => setCompensation(e.target.value)} /><FieldDescription>Never shown to employers.</FieldDescription></Field>
          </FieldGroup></section>}
        {step === 2 && <section className="flex flex-col gap-6"><h1 className="text-3xl font-medium text-balance">How many decisions at once?</h1><p className="-mt-3 text-muted-foreground">Your active decision capacity — not a lifetime limit. As you decide, new introductions can arrive.</p>
          <ToggleGroup type="single" variant="outline" className="flex-wrap" value={capacity} onValueChange={(v) => v && setCapacity(v)} aria-label="Active decision capacity">{Array.from({ length: 10 }, (_, i) => String(i + 1)).map((n) => <ToggleGroupItem key={n} value={n} className="w-10">{n}</ToggleGroupItem>)}</ToggleGroup></section>}
        <div className="flex justify-between">
          <Button variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)}><ArrowLeft data-icon="inline-start" />Back</Button>
          <Button onClick={next} disabled={titleError}>{step === STEPS.length - 1 ? 'Finish' : 'Continue'}<ArrowRight data-icon="inline-end" /></Button>
        </div>
      </div>
    </EntryFrame>
  )
}
