'use client'
import { useState } from 'react'
import Link from 'next/link'
import {
  BadgeCheck,
  CircleDashed,
  EyeOff,
  FileCheck2,
  FileText,
  HeartHandshake,
  MessageSquare,
  Plus,
  ShieldCheck,
  ShieldOff,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { CompanyMark } from '@/components/brand'
import {
  EmptyNote,
  PageHeader,
  Progression,
  SectionTitle,
} from '@/components/workspace/kit'
import { useWorkspace } from '@/lib/workspace'
import type { Offer, Stage } from '@/lib/contracts'

const STAGES: Stage[] = [
  'Mutual interest',
  'Interviewing',
  'Offer',
  'Employment confirmed',
]

export function MatchesPage() {
  const { data } = useWorkspace()
  const awaiting = data.opportunities.filter(
    (opportunity) =>
      data.decisions[opportunity.id] === 'interested' &&
      !data.matches.some((match) => match.opportunityId === opportunity.id),
  )
  return (
    <>
      <PageHeader
        eyebrow="Mutual interest"
        title="My matches"
        description="Both sides said yes. Here’s where each conversation stands."
      />
      {data.matches.length === 0 ? (
        <EmptyNote
          icon={HeartHandshake}
          title="No mutual matches yet"
          description="When an employer shares interest back, the match appears here."
        />
      ) : (
        <ul className="flex flex-col gap-4">
          {data.matches.map((match) => (
            <li key={match.id} className="panel flex flex-col gap-5 p-5 md:p-6">
              <div className="flex flex-wrap items-center gap-4">
                <CompanyMark name={match.company} />
                <div className="flex-1">
                  <p className="font-medium">{match.role}</p>
                  <p className="text-sm text-muted-foreground">
                    {match.company} · Updated {match.updated.toLowerCase()}
                  </p>
                </div>
                <Badge variant="outline">
                  {match.state?.replaceAll('_', ' ') || match.stage}
                </Badge>
                <Button variant="outline" size="sm" asChild>
                  <Link href="/candidate/messages">
                    <MessageSquare data-icon="inline-start" />
                    Message
                  </Link>
                </Button>
                {match.stage === 'Offer' && (
                  <Button size="sm" asChild>
                    <Link href="/candidate/offers">
                      <FileText data-icon="inline-start" />
                      Review offer
                    </Link>
                  </Button>
                )}
              </div>
              <Progression
                steps={STAGES}
                current={
                  match.stage === 'Employment confirmed'
                    ? STAGES.length
                    : STAGES.indexOf(match.stage)
                }
              />
            </li>
          ))}
        </ul>
      )}
      {awaiting.length > 0 && (
        <section className="mt-10">
          <SectionTitle
            title="Awaiting the employer"
            description="You shared interest. A match forms only if they share interest too."
          />
          <ul className="panel divide-y">
            {awaiting.map((opportunity) => (
              <li key={opportunity.id} className="flex items-center gap-4 p-5">
                <CompanyMark
                  name={opportunity.company}
                  className="size-9 text-base"
                />
                <span className="flex-1 text-sm">
                  <span className="font-medium">{opportunity.title}</span> ·{' '}
                  {opportunity.company}
                </span>
                <Badge variant="outline">
                  <CircleDashed data-icon="inline-start" />
                  Awaiting response
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

export function CandidateOffersPage() {
  const { data } = useWorkspace()
  return (
    <>
      <PageHeader
        eyebrow="Formal offers"
        title="Offers"
        description="Written offers from employers. Review the complete terms before accepting."
      />
      {data.offers.length === 0 ? (
        <EmptyNote
          icon={FileText}
          title="No offers yet"
          description="Offers appear here after interviews with mutually matched employers."
        />
      ) : (
        <div className="flex flex-col gap-6">
          {data.offers.map((offer) => (
            <CandidateOffer key={offer.id} offer={offer} />
          ))}
        </div>
      )}
    </>
  )
}

function CandidateOffer({ offer }: { offer: Offer }) {
  const { data, execute } = useWorkspace()
  const [busy, setBusy] = useState(false)
  const [startedAt, setStartedAt] = useState('')
  const [reference, setReference] = useState('')
  const [reported, setReported] = useState(false)
  const match = data.matches.find((item) => item.id === offer.matchId)
  const confirmed = match?.stage === 'Employment confirmed'
  const expired =
    !!offer.expiresAt && new Date(offer.expiresAt).getTime() <= Date.now()
  const canAnswer =
    offer.status === 'Awaiting response' &&
    !expired &&
    (!offer.backendStatus || offer.backendStatus === 'OFFERED')
  async function respond(status: 'Accepted' | 'Declined') {
    if (busy) return
    setBusy(true)
    await execute(
      'offer.answer',
      { id: offer.id, status, expected_version: offer.version },
      status === 'Accepted'
        ? 'Offer accepted. Your employment start is recorded separately.'
        : 'Offer declined.',
    )
    setBusy(false)
  }
  async function reportStart(event: React.FormEvent) {
    event.preventDefault()
    const date = new Date(startedAt)
    if (
      busy ||
      !offer.matchId ||
      !startedAt ||
      !Number.isFinite(date.getTime()) ||
      date.getTime() > Date.now() ||
      reference.trim().length < 10
    )
      return
    setBusy(true)
    const saved = await execute(
      'start.report',
      {
        matchId: offer.matchId,
        start_at: date.toISOString(),
        evidence_reference: reference.trim(),
        expected_version: match?.cycleVersion ?? offer.cycleVersion,
      },
      'Employment start reported for independent verification.',
    )
    if (saved) setReported(true)
    setBusy(false)
  }
  return (
    <article className="panel max-w-3xl overflow-hidden">
      <div className="flex flex-wrap items-center gap-4 border-b p-6">
        <CompanyMark name={offer.company} />
        <div className="flex-1">
          <p className="text-lg font-medium">{offer.role}</p>
          <p className="text-sm text-muted-foreground">{offer.company}</p>
        </div>
        <Badge
          variant={
            offer.status === 'Awaiting response' ? 'outline' : 'secondary'
          }
        >
          {confirmed
            ? 'Employment confirmed'
            : expired && offer.status === 'Awaiting response'
              ? 'Expired'
              : offer.backendStatus?.replaceAll('_', ' ') || offer.status}
        </Badge>
      </div>
      <dl className="grid gap-6 p-6 sm:grid-cols-3">
        {[
          ['Compensation', offer.salary],
          ['Proposed start', offer.start],
          ['Respond by', offer.deadline],
        ].map(([key, value]) => (
          <div key={key}>
            <dt className="text-xs text-muted-foreground">{key}</dt>
            <dd className="mt-1 font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      <section className="border-t p-6">
        <h2 className="mb-3 text-sm font-medium">Written offer terms</h2>
        <p className="whitespace-pre-wrap text-sm text-muted-foreground">
          {offer.terms ||
            'Written terms are unavailable. Refresh before responding.'}
        </p>
      </section>
      {canAnswer && (
        <div className="flex flex-wrap items-center justify-end gap-2 border-t bg-muted/40 p-4">
          <ConfirmButton
            disabled={busy || !offer.terms}
            variant="outline"
            label="Decline"
            title="Decline this offer?"
            description={`${offer.company} will receive your formal response.`}
            onConfirm={() => respond('Declined')}
          />
          <ConfirmButton
            disabled={busy || !offer.terms}
            label="Accept offer"
            title="Accept this offer?"
            description="I have reviewed the written terms above and accept this offer. My actual start requires separate independent verification."
            onConfirm={() => respond('Accepted')}
          />
        </div>
      )}
      {offer.status === 'Accepted' && !confirmed && (
        <section className="border-t p-6">
          <h2 className="text-sm font-medium">Report your actual start</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Submit this after you have started. An independent verifier must
            corroborate it before employment is confirmed.
          </p>
          {reported || match?.startReport ? (
            <p role="status" className="mt-4 text-sm text-primary">
              Start reported. Independent verification is pending.
            </p>
          ) : (
            <form onSubmit={reportStart} className="mt-4 flex flex-col gap-4">
              <Field>
                <FieldLabel htmlFor={`start-${offer.id}`}>
                  Actual start date and time
                </FieldLabel>
                <Input
                  id={`start-${offer.id}`}
                  type="datetime-local"
                  required
                  value={startedAt}
                  onChange={(event) => setStartedAt(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor={`reference-${offer.id}`}>
                  Evidence reference
                </FieldLabel>
                <Input
                  id={`reference-${offer.id}`}
                  required
                  minLength={10}
                  maxLength={1000}
                  placeholder="Reference to a start record that a verifier can check"
                  value={reference}
                  onChange={(event) => setReference(event.target.value)}
                />
              </Field>
              <Button
                className="self-end"
                type="submit"
                disabled={
                  busy ||
                  !offer.matchId ||
                  !startedAt ||
                  reference.trim().length < 10 ||
                  new Date(startedAt).getTime() > Date.now()
                }
              >
                {busy ? 'Submitting…' : 'Report employment start'}
              </Button>
            </form>
          )}
        </section>
      )}
    </article>
  )
}

function ConfirmButton({
  label,
  title,
  description,
  onConfirm,
  disabled,
  variant = 'default',
}: {
  label: string
  title: string
  description: string
  onConfirm: () => void
  disabled?: boolean
  variant?: 'default' | 'outline'
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button disabled={disabled} variant={variant}>
          {label}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>{label}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ProfilePage() {
  const { data, execute } = useWorkspace()
  const profile = data.profile
  const [draftSummary, setDraftSummary] = useState<string | null>(null)
  const summary = draftSummary ?? profile.summary
  const [skill, setSkill] = useState('')
  const [busy, setBusy] = useState(false)
  async function run(
    action: string,
    payload: Record<string, unknown>,
    message: string,
  ) {
    if (busy) return false
    setBusy(true)
    const saved = await execute(
      action,
      { expected_version: profile.version, ...payload },
      message,
    )
    setBusy(false)
    return saved
  }
  if (!profile.id)
    return (
      <>
        <PageHeader
          eyebrow="About you"
          title="Profile & skills"
          description="Set up your profile and choose your introduction preferences."
        />
        <Button asChild>
          <Link href="/onboarding/candidate">Set up your profile</Link>
        </Button>
      </>
    )
  return (
    <>
      <PageHeader
        eyebrow="About you"
        title="Profile & skills"
        description="Your profile and preferences guide introductions. You control when it is active."
        actions={
          <Button variant="outline" asChild>
            <Link href="/onboarding/candidate">Edit preferences</Link>
          </Button>
        }
      />
      <div className="grid max-w-5xl gap-10 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-10">
          <section>
            <SectionTitle title="Summary" />
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="summary">Professional summary</FieldLabel>
                <Textarea
                  id="summary"
                  maxLength={10000}
                  rows={4}
                  value={summary}
                  onChange={(event) => setDraftSummary(event.target.value)}
                />
                <FieldDescription>
                  {summary.length}/10000 characters
                </FieldDescription>
              </Field>
              <Button
                className="self-start"
                disabled={
                  busy || summary === profile.summary || summary.length > 10000
                }
                onClick={async () => {
                  if (
                    await run(
                      'candidate.save',
                      { patch: { summary } },
                      'Profile updated.',
                    )
                  )
                    setDraftSummary(null)
                }}
              >
                Save summary
              </Button>
            </FieldGroup>
          </section>
          <section>
            <SectionTitle
              title="Skills"
              description="These are self-reported. Evidence verification is handled separately."
            />
            <div className="mb-4 flex flex-wrap gap-2">
              {profile.skills.map((name) => (
                <Badge key={name} variant="secondary" className="gap-1 pr-1">
                  {name}
                  <button
                    disabled={busy}
                    aria-label={`Remove ${name}`}
                    className="rounded-full p-0.5 hover:bg-background"
                    onClick={() =>
                      run(
                        'candidate.skill.remove',
                        {
                          name,
                          id: data.backend.skills.find(
                            (item) => item.name === name,
                          )?.id,
                          expected_version: data.backend.skills.find(
                            (item) => item.name === name,
                          )?.version,
                        },
                        `Removed ${name}.`,
                      )
                    }
                  >
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
            </div>
            <form
              className="flex max-w-sm gap-2"
              onSubmit={async (event) => {
                event.preventDefault()
                const name = skill.trim()
                if (
                  name &&
                  !profile.skills.some(
                    (item) => item.toLowerCase() === name.toLowerCase(),
                  ) &&
                  (await run('candidate.skill.add', { name }, `Added ${name}.`))
                )
                  setSkill('')
              }}
            >
              <Input
                aria-label="Add a skill"
                placeholder="Add a skill"
                maxLength={100}
                value={skill}
                onChange={(event) => setSkill(event.target.value)}
              />
              <Button
                disabled={busy || !skill.trim()}
                type="submit"
                variant="outline"
                size="icon"
                aria-label="Add skill"
              >
                <Plus />
              </Button>
            </form>
          </section>
          <section>
            <SectionTitle
              title="Requirements & preferences"
              description="Update work arrangement, location, role family and compensation in your profile preferences."
            />
            <dl className="panel divide-y text-sm">
              {[
                ['Role family', profile.roles?.join(', ') || 'Not set'],
                ['Location', profile.location],
                ['Work arrangement', profile.remote],
                ['Availability', profile.availability],
                ['Experience', profile.experience],
                [
                  'Compensation expectation',
                  `${profile.compensation} · private`,
                ],
              ].map(([key, value]) => (
                <div key={key} className="flex flex-col gap-1 p-4">
                  <dt className="text-xs text-muted-foreground">{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
        <aside className="flex flex-col gap-5">
          <section className="panel p-5">
            <h2 className="text-sm font-medium tracking-normal">
              Profile visibility
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Status: {profile.state?.replaceAll('_', ' ') || 'Draft'}. Pausing
              stops new decision cards. Existing mutual conversations remain
              available.
            </p>
            <Button
              className="mt-4"
              variant={profile.state === 'ACTIVE' ? 'outline' : 'default'}
              disabled={busy}
              onClick={() =>
                run(
                  profile.state === 'ACTIVE'
                    ? 'candidate.pause'
                    : 'candidate.activate',
                  {},
                  profile.state === 'ACTIVE'
                    ? 'Profile paused.'
                    : 'Profile activated.',
                )
              }
            >
              {profile.state === 'ACTIVE'
                ? 'Pause profile'
                : 'Activate profile'}
            </Button>
          </section>
          <section className="panel p-5">
            <h2 className="text-sm font-medium tracking-normal">
              Active decision capacity
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              How many opportunities can await your decision at once. The
              backend enforces this limit.
            </p>
            <ToggleGroup
              disabled={busy}
              type="single"
              variant="outline"
              size="sm"
              className="mt-4 flex-wrap"
              value={String(profile.capacity)}
              onValueChange={(value) =>
                value &&
                run(
                  'candidate.preferences',
                  { capacity: Number(value) },
                  `Capacity set to ${value} at a time.`,
                )
              }
              aria-label="Active decision capacity"
            >
              {Array.from({ length: 10 }, (_, index) => String(index + 1)).map(
                (number) => (
                  <ToggleGroupItem key={number} value={number} className="w-9">
                    {number}
                  </ToggleGroupItem>
                ),
              )}
            </ToggleGroup>
          </section>
          <p className="flex gap-2 text-xs text-muted-foreground">
            <EyeOff className="size-3.5 shrink-0" />
            Your compensation floor is never shown to employers.
          </p>
        </aside>
      </div>
    </>
  )
}

export function EvidencePage() {
  const { data, execute } = useWorkspace()
  const [claimType, setClaimType] = useState('SKILL')
  const [keys, setKeys] = useState('')
  const [statement, setStatement] = useState('')
  const [purpose, setPurpose] = useState('')
  const [busy, setBusy] = useState(false)
  const requirementKeys = [
    ...new Set(
      keys
        .split(',')
        .map((key) => key.trim())
        .filter(Boolean),
    ),
  ]
  const valid =
    requirementKeys.length > 0 &&
    requirementKeys.length <= 20 &&
    requirementKeys.every((key) => key.length <= 100) &&
    statement.trim().length >= 10 &&
    purpose.trim().length >= 10
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!valid || busy) return
    setBusy(true)
    const saved = await execute(
      'evidence.create',
      {
        claim_type: claimType,
        requirement_keys: requirementKeys,
        statement: statement.trim(),
        job_related_purpose: purpose.trim(),
        expected_version: data.profile.version,
      },
      'Evidence claim submitted. Independent verification is pending.',
    )
    if (saved) {
      setStatement('')
      setKeys('')
      setPurpose('')
    }
    setBusy(false)
  }
  return (
    <>
      <PageHeader
        eyebrow="Your credentials"
        title="Qualification evidence"
        description="Submit factual claims for independent verification. Share evidence only with explicit consent."
      />
      {data.evidence.length === 0 ? (
        <EmptyNote
          icon={FileCheck2}
          title="No evidence claims yet"
          description="Add a claim below so an independent verifier can review it."
        />
      ) : (
        <ul className="panel max-w-3xl divide-y">
          {data.evidence.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-4 p-5">
              <span className="flex size-10 items-center justify-center rounded-lg bg-secondary text-primary">
                {item.status === 'Verified' ? (
                  <BadgeCheck className="size-5" />
                ) : (
                  <FileCheck2 className="size-5" />
                )}
              </span>
              <div className="flex-1">
                <p className="font-medium">{item.name}</p>
                <p className="text-sm text-muted-foreground">{item.issuer}</p>
              </div>
              <Badge
                variant={item.status === 'Verified' ? 'secondary' : 'outline'}
              >
                {item.backendStatus?.replaceAll('_', ' ') || item.status}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {data.profile.id ? (
        <form
          onSubmit={submit}
          className="panel mt-8 flex max-w-3xl flex-col gap-5 p-6"
        >
          <h2 className="text-lg font-medium">Submit an evidence claim</h2>
          <Field>
            <FieldLabel htmlFor="claim-type">Claim type</FieldLabel>
            <select
              id="claim-type"
              className="h-10 rounded-lg border bg-background px-3 text-sm"
              value={claimType}
              onChange={(event) => setClaimType(event.target.value)}
            >
              {[
                'SKILL',
                'PROJECT',
                'EMPLOYMENT',
                'EDUCATION',
                'LICENSE',
                'WORK_AUTHORIZATION',
              ].map((type) => (
                <option key={type} value={type}>
                  {type.replaceAll('_', ' ')}
                </option>
              ))}
            </select>
          </Field>
          <Field>
            <FieldLabel htmlFor="requirement-keys">Requirement keys</FieldLabel>
            <Input
              id="requirement-keys"
              required
              placeholder="For example: python, system_design"
              value={keys}
              onChange={(event) => setKeys(event.target.value)}
            />
            <FieldDescription>
              Comma-separated keys for the job requirements this evidence
              supports (up to 20).
            </FieldDescription>
          </Field>
          <Field>
            <FieldLabel htmlFor="claim-statement">Factual statement</FieldLabel>
            <Textarea
              id="claim-statement"
              required
              minLength={10}
              maxLength={5000}
              value={statement}
              onChange={(event) => setStatement(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="claim-purpose">Job-related purpose</FieldLabel>
            <Textarea
              id="claim-purpose"
              required
              minLength={10}
              maxLength={500}
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
            />
          </Field>
          <Button className="self-end" type="submit" disabled={busy || !valid}>
            {busy ? 'Submitting…' : 'Submit claim'}
          </Button>
        </form>
      ) : (
        <Button className="mt-6" asChild>
          <Link href="/onboarding/candidate">Create your profile first</Link>
        </Button>
      )}
      <p className="mt-4 max-w-3xl text-xs text-muted-foreground">
        A submitted claim is not verified evidence. An independent verifier
        reviews evidence before a verified status can appear.
      </p>
    </>
  )
}

export function PrivacyPage() {
  const { data, execute } = useWorkspace()
  const [busy, setBusy] = useState(false)
  const requests = data.backend.policies
    .filter(
      (policy) =>
        policy.state === 'AUTHORIZED' &&
        new Date(policy.expires_at).getTime() > Date.now(),
    )
    .flatMap((policy) =>
      Object.entries(policy.scope).flatMap(([vacancyId, scope]) => {
        const vacancy = data.backend.vacancies.find(
          (item) => item.id === vacancyId,
        )
        return vacancy &&
          vacancy.version === scope.version &&
          vacancy.terms_hash === scope.terms_hash
          ? [{ policy, vacancy }]
          : []
      }),
    )
  async function revoke(id: string, version?: number) {
    if (busy) return
    setBusy(true)
    await execute(
      'consent.revoke',
      { id, expected_version: version },
      'Consent revoked. Access dependent on this consent is withdrawn.',
    )
    setBusy(false)
  }
  return (
    <>
      <PageHeader
        eyebrow="You’re in control"
        title="Privacy & consent"
        description="Review each recipient, purpose and expiry before sharing. Revoke an active disclosure anytime."
      />
      <div className="flex max-w-3xl flex-col gap-10">
        <section>
          <SectionTitle
            title="Agreement requests"
            description="An employer’s authorized terms require your own explicit consent. This is not an offer or an employment guarantee."
          />
          {requests.length === 0 ? (
            <EmptyNote
              icon={ShieldCheck}
              title="No requests right now"
              description="Authorized terms for your matched roles appear here."
            />
          ) : (
            <div className="flex flex-col gap-4">
              {requests.map(({ policy, vacancy }) => (
                <TermsConsentCard
                  key={`${policy.id}-${policy.version}-${vacancy.id}-${vacancy.version}`}
                  policy={policy}
                  vacancy={vacancy}
                />
              ))}
            </div>
          )}
        </section>
        <section>
          <SectionTitle
            title="Share verified evidence"
            description="Choose the exact role, recipient, evidence and expiry. This creates a separate disclosure consent."
          />
          <EvidenceConsentForm
            key={`${data.backend.vacancies.map((item) => `${item.id}:${item.version}`).join(`,`)}-${data.backend.evidence.map((item) => `${item.id}:${item.version}`).join(`,`)}`}
          />
        </section>
        <section>
          <SectionTitle title="Consent ledger" />
          {data.consents.length === 0 ? (
            <EmptyNote
              icon={ShieldCheck}
              title="No disclosure consents"
              description="Your consent ledger will list every recipient and expiry here."
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {data.consents.map((consent) => (
                <li key={consent.id} className="panel flex flex-col gap-4 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-medium">{consent.label}</p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Recipient:{' '}
                        <span className="text-foreground">
                          {consent.recipient}
                        </span>{' '}
                        · Expires {consent.expires}
                      </p>
                    </div>
                    <Badge variant={consent.granted ? 'secondary' : 'outline'}>
                      {consent.granted ? 'Active consent' : 'Inactive'}
                    </Badge>
                  </div>
                  <p className="rounded-lg bg-muted p-3 text-sm">
                    <span className="font-medium">Exact purpose: </span>
                    {consent.purpose}
                  </p>
                  {consent.granted && (
                    <div className="flex justify-end">
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button disabled={busy} size="sm" variant="outline">
                            <ShieldOff data-icon="inline-start" />
                            Revoke
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>
                              Revoke this disclosure?
                            </AlertDialogTitle>
                            <AlertDialogDescription>
                              {consent.recipient} will lose access under “
                              {consent.label}”. Steps that depend on it may
                              pause.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Keep sharing</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={() =>
                                revoke(consent.id, consent.version)
                              }
                            >
                              Revoke
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
        <Alert>
          <EyeOff />
          <AlertTitle>Your private information</AlertTitle>
          <AlertDescription>
            Your compensation floor stays private. Evidence disclosures require
            consent for the exact role, recipient, purpose and expiry.
          </AlertDescription>
        </Alert>
      </div>
    </>
  )
}

function TermsConsentCard({
  policy,
  vacancy,
}: {
  policy: import('@/lib/workspace').ApiSchema['PolicyOut']
  vacancy: import('@/lib/workspace').ApiSchema['VacancyOut']
}) {
  const { data, execute } = useWorkspace()
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const scope =
    policy.stage === 'CONDITIONAL_OFFER'
      ? 'CONDITIONAL_TERMS'
      : 'PRELIMINARY_INTEREST'
  const consent = data.backend.consents.terms.find(
    (item) =>
      item.vacancy_id === vacancy.id &&
      item.role_version === vacancy.version &&
      item.terms_hash === vacancy.terms_hash &&
      item.scope === scope &&
      !item.revoked_at &&
      new Date(item.expires_at).getTime() > Date.now(),
  )
  const [expiresAt] = useState(() =>
    new Date(
      Math.min(
        new Date(policy.expires_at).getTime(),
        Date.now() + 7 * 86400000,
      ),
    ).toISOString(),
  )
  const company =
    data.vacancies.find((item) => item.id === vacancy.id)?.company || 'Employer'
  async function confirm() {
    if (busy || !checked) return
    setBusy(true)
    const saved = await execute(
      'consent.terms',
      {
        vacancyId: vacancy.id,
        scope,
        expected_version: vacancy.version,
        candidate_expected_version: data.profile.version,
        terms_hash: vacancy.terms_hash,
        checkbox_confirmed: true,
        expires_at: expiresAt,
      },
      'Consent to these exact terms recorded.',
    )
    if (saved) setChecked(false)
    setBusy(false)
  }
  return (
    <article className="panel p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-medium">
            {vacancy.title} · Role v{vacancy.version}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {company} · {policy.stage.replaceAll('_', ' ')}
          </p>
        </div>
        <Badge variant={consent ? 'secondary' : 'outline'}>
          {consent ? 'Active consent recorded' : 'Awaiting your review'}
        </Badge>
      </div>
      <p className="mb-4 whitespace-pre-wrap text-sm">{policy.policy_text}</p>
      <dl className="grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">Compensation</dt>
          <dd className="mt-1">
            {vacancy.pay_min}–{vacancy.pay_max} {vacancy.currency} /{' '}
            {vacancy.compensation_period.toLowerCase()}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Arrangement</dt>
          <dd className="mt-1">
            {vacancy.work_mode.toLowerCase()} ·{' '}
            {vacancy.location_region || 'Remote'}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Consent scope</dt>
          <dd className="mt-1">{scope.replaceAll('_', ' ').toLowerCase()}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Consent expires</dt>
          <dd className="mt-1">
            {new Date(consent?.expires_at || expiresAt).toLocaleString()}
          </dd>
        </div>
      </dl>
      {vacancy.requirements.length > 0 && (
        <ul className="mt-4 list-disc pl-5 text-sm text-muted-foreground">
          {vacancy.requirements.map((requirement) => (
            <li key={requirement.id}>
              {requirement.description} ({requirement.kind.toLowerCase()})
            </li>
          ))}
        </ul>
      )}
      {!consent && (
        <>
          <label className="mt-6 flex items-start gap-3 text-sm">
            <Checkbox
              checked={checked}
              onCheckedChange={(value) => setChecked(value === true)}
            />
            <span>
              I consent to these exact role terms until the expiry shown above.
              Evidence sharing requires a separate disclosure consent.
            </span>
          </label>
          <div className="mt-6 flex justify-end">
            <Button disabled={busy || !checked} onClick={confirm}>
              {busy ? 'Saving…' : 'Consent to these terms'}
            </Button>
          </div>
        </>
      )}
    </article>
  )
}

function EvidenceConsentForm() {
  const { data, execute } = useWorkspace()
  const vacancies = data.backend.vacancies.filter(
    (vacancy) =>
      vacancy.state === 'ACTIVE' &&
      (data.backend.matches.some((match) => match.vacancy.id === vacancy.id) ||
        data.opportunities.some(
          (opportunity) => opportunity.id === vacancy.id,
        )),
  )
  const claims = data.backend.evidence.filter(
    (claim) =>
      claim.status === 'VERIFIED' &&
      claim.expires_at &&
      new Date(claim.expires_at).getTime() > Date.now(),
  )
  const [vacancyId, setVacancyId] = useState('')
  const [claimId, setClaimId] = useState('')
  const [kind, setKind] = useState('DISCLOSE_SUMMARY')
  const [purpose, setPurpose] = useState('')
  const [expiry, setExpiry] = useState('')
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const vacancy = vacancies.find((item) => item.id === vacancyId)
  const claim = claims.find((item) => item.id === claimId)
  const date = new Date(expiry)
  const validDate =
    !!expiry &&
    Number.isFinite(date.getTime()) &&
    date.getTime() > Date.now() &&
    date.getTime() <= Date.now() + 30 * 86400000 &&
    !!claim?.expires_at &&
    date.getTime() <= new Date(claim.expires_at).getTime()
  const valid =
    !!vacancy &&
    !!claim &&
    checked &&
    purpose.trim().length >= 10 &&
    validDate &&
    (kind !== 'DISCLOSE_DOCUMENT' || claim.has_document)
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!valid || !vacancy || !claim || busy) return
    setBusy(true)
    const saved = await execute(
      'consent.evidence',
      {
        vacancyId: vacancy.id,
        claimId: claim.id,
        kind,
        consent_text: purpose.trim(),
        expires_at: date.toISOString(),
        checkbox_confirmed: true,
        expected_version: vacancy.version,
        terms_hash: vacancy.terms_hash,
        claim_expected_version: claim.version,
        org_id: vacancy.org_id,
      },
      'Evidence disclosure consent recorded.',
    )
    if (saved) {
      setChecked(false)
      setPurpose('')
    }
    setBusy(false)
  }
  if (claims.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        No current verified evidence is available to share.{' '}
        <Link href="/candidate/evidence" className="text-primary underline">
          Manage your evidence claims
        </Link>
        .
      </p>
    )
  if (vacancies.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        A current introduction or matched role is required before sharing
        evidence.
      </p>
    )
  return (
    <form onSubmit={submit} className="panel flex flex-col gap-5 p-6">
      <Field>
        <FieldLabel htmlFor="consent-vacancy">Role and recipient</FieldLabel>
        <select
          id="consent-vacancy"
          required
          className="h-10 rounded-lg border bg-background px-3 text-sm"
          value={vacancyId}
          onChange={(event) => {
            setVacancyId(event.target.value)
            setChecked(false)
          }}
        >
          <option value="">Choose an exact role</option>
          {vacancies.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title} ·{' '}
              {data.vacancies.find((view) => view.id === item.id)?.company ||
                'Employer'}{' '}
              · v{item.version}
            </option>
          ))}
        </select>
      </Field>
      <Field>
        <FieldLabel htmlFor="consent-claim">Verified evidence</FieldLabel>
        <select
          id="consent-claim"
          required
          className="h-10 rounded-lg border bg-background px-3 text-sm"
          value={claimId}
          onChange={(event) => {
            setClaimId(event.target.value)
            setChecked(false)
            setKind('DISCLOSE_SUMMARY')
          }}
        >
          <option value="">Choose evidence to disclose</option>
          {claims.map((item) => (
            <option key={item.id} value={item.id}>
              {item.claim_type} · {item.requirement_keys.join(', ')} · v
              {item.version}
            </option>
          ))}
        </select>
      </Field>
      <Field>
        <FieldLabel htmlFor="consent-kind">Disclosure scope</FieldLabel>
        <select
          id="consent-kind"
          className="h-10 rounded-lg border bg-background px-3 text-sm"
          value={kind}
          onChange={(event) => {
            setKind(event.target.value)
            setChecked(false)
          }}
        >
          <option value="DISCLOSE_SUMMARY">Verified summary only</option>
          <option value="DISCLOSE_DOCUMENT" disabled={!claim?.has_document}>
            Verified document and summary
          </option>
        </select>
      </Field>
      <Field>
        <FieldLabel htmlFor="consent-purpose">
          Exact disclosure purpose
        </FieldLabel>
        <Textarea
          id="consent-purpose"
          required
          minLength={10}
          maxLength={2000}
          value={purpose}
          onChange={(event) => {
            setPurpose(event.target.value)
            setChecked(false)
          }}
        />
      </Field>
      <Field>
        <FieldLabel htmlFor="consent-expiry">Consent expiry</FieldLabel>
        <Input
          id="consent-expiry"
          required
          type="datetime-local"
          value={expiry}
          onChange={(event) => {
            setExpiry(event.target.value)
            setChecked(false)
          }}
        />
        <FieldDescription>
          Within 30 days and before the evidence expires
          {claim?.expires_at
            ? ` (${new Date(claim.expires_at).toLocaleString()})`
            : ''}
          .
        </FieldDescription>
      </Field>
      <label className="flex items-start gap-3 text-sm">
        <Checkbox
          checked={checked}
          onCheckedChange={(value) => setChecked(value === true)}
        />
        <span>
          I authorize this exact recipient to access the selected evidence for
          the purpose and duration specified above. I can revoke this consent.
        </span>
      </label>
      <Button className="self-end" type="submit" disabled={busy || !valid}>
        {busy ? 'Saving…' : 'Grant disclosure consent'}
      </Button>
    </form>
  )
}
