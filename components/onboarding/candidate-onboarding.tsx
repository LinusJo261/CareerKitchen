"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FileText,
  LoaderCircle,
  Plus,
  ShieldCheck,
  X,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Progression } from "@/components/workspace/kit";
import {
  sendWorkspaceCommand,
  useWorkspace,
  WorkspaceError,
  type ApiSchema,
  type WorkspaceState,
} from "@/lib/workspace";
import {
  EMPLOYMENT_OPTIONS,
  MAX_RESUME_BYTES,
  ONBOARDING_STEPS,
  WORK_OPTIONS,
  emptyEducation,
  emptyExperience,
  labels,
  onboardingDraft,
  onboardingErrors,
  skillError,
  type OnboardingDraft,
} from "@/lib/onboarding";
import { onboardingSaveState, saveOnboarding } from "@/lib/onboarding-save";
import { onboardingLoadState } from "@/lib/onboarding-load";

function Frame({
  children,
  loadWarning,
  onRetry,
}: {
  children: ReactNode;
  loadWarning?: string;
  onRetry?: () => void;
}) {
  return (
    <main className="min-h-dvh">
      <header className="page-width flex min-h-20 items-center justify-between gap-4 py-4">
        <Brand />
        <Badge variant="outline">Your profile</Badge>
      </header>
      <div className="page-width py-8 pb-24 md:py-12">
        {loadWarning && (
          <Alert className="mx-auto mb-8 max-w-6xl">
            <AlertDescription
              role="status"
              className="flex flex-wrap items-center justify-between gap-3"
            >
              <span>{loadWarning}</span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onRetry}
              >
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {children}
      </div>
    </main>
  );
}

export function CandidateOnboarding() {
  const { data, isLoading, error, refresh } = useWorkspace();
  const loadState = onboardingLoadState(!!data.session, error, "candidate");
  if (isLoading && !data.session)
    return (
      <Frame>
        <div
          role="status"
          className="mx-auto flex max-w-lg items-center gap-3 py-16"
        >
          <LoaderCircle className="size-5 animate-spin" />
          Loading your account…
        </div>
      </Frame>
    );
  if (
    !data.session ||
    (loadState.kind !== "ready" && loadState.kind !== "warning")
  )
    return (
      <Frame>
        <div className="mx-auto max-w-lg py-12">
          <h1 className="text-3xl">{loadState.title}</h1>
          <p role="alert" className="mt-4 text-muted-foreground">
            {loadState.message}
          </p>
          <div className="mt-6 flex gap-3">
            {loadState.kind === "sign-in" ? (
              <Button asChild>
                <Link href="/sign-in?role=candidate">Sign in</Link>
              </Button>
            ) : (
              <Button
                variant="outline"
                onClick={() => refresh().catch(() => undefined)}
              >
                Try again
              </Button>
            )}
          </div>
        </div>
      </Frame>
    );
  return (
    <CandidateWizard
      key={data.session.id}
      initial={data}
      refresh={refresh}
      loadWarning={
        loadState.kind === "warning"
          ? `${loadState.title} ${loadState.message}`
          : undefined
      }
    />
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  help,
  type = "text",
  maxLength,
  placeholder,
  autoComplete,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  help?: string;
  type?: string;
  maxLength?: number;
  placeholder?: string;
  autoComplete?: string;
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        maxLength={maxLength}
        placeholder={placeholder}
        autoComplete={autoComplete}
        aria-describedby={help ? `${id}-help` : undefined}
      />
      {help && <FieldDescription id={`${id}-help`}>{help}</FieldDescription>}
    </Field>
  );
}
function ChoiceList({
  legend,
  options,
  value,
  onChange,
}: {
  legend: string;
  options: readonly (readonly [string, string])[];
  value: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-3 text-sm font-medium">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map(([id, label]) => (
          <label key={id} className="relative cursor-pointer">
            <input
              type="checkbox"
              checked={value.includes(id)}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...value, id]
                    : value.filter((item) => item !== id),
                )
              }
              className="peer sr-only"
            />
            <span className="flex items-center gap-2 rounded-lg border px-4 py-3 text-sm transition-colors peer-checked:border-primary peer-checked:bg-secondary peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring">
              {value.includes(id) && (
                <Check aria-hidden="true" className="size-3.5" />
              )}
              {label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-5">
      <div>
        <h2 className="text-xl font-medium">{title}</h2>
        {description && (
          <p className="mt-2 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {children}
    </section>
  );
}

function CandidateWizard({
  initial,
  refresh,
  loadWarning,
}: {
  initial: WorkspaceState;
  refresh: () => Promise<unknown>;
  loadWarning?: string;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState(() =>
    onboardingDraft(
      initial.backend.candidate,
      initial.backend.skills.map((item) => item.name),
    ),
  );
  const [step, setStep] = useState(0);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saveStatus, setSaveStatus] = useState("");
  const [skill, setSkill] = useState("");
  const [skillNotice, setSkillNotice] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [resumeError, setResumeError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const previousStep = useRef(0);
  const saveState = useRef(
    onboardingSaveState(
      initial.backend.candidate?.version ?? 0,
      initial.backend.skills,
    ),
  );
  const dirty = useRef(false);
  const errors = attempted ? onboardingErrors(draft, step) : [];

  useEffect(() => {
    if (previousStep.current !== step) heading.current?.focus();
    previousStep.current = step;
  }, [step]);
  useEffect(() => {
    function leaving(event: BeforeUnloadEvent) {
      if (dirty.current) event.preventDefault();
    }
    window.addEventListener("beforeunload", leaving);
    return () => window.removeEventListener("beforeunload", leaving);
  }, []);
  function update<K extends keyof OnboardingDraft>(
    key: K,
    value: OnboardingDraft[K],
  ) {
    dirty.current = true;
    setDraft((current) => ({
      ...current,
      [key]: value,
      ...(key !== "profileConfirmed" &&
      key !== "termsAccepted" &&
      key !== "privacyAccepted"
        ? { profileConfirmed: false }
        : {}),
    }));
  }
  function experience(
    index: number,
    key: keyof OnboardingDraft["experiences"][number],
    value: string | boolean,
  ) {
    update(
      "experiences",
      draft.experiences.map((item, i) =>
        i === index ? { ...item, [key]: value } : item,
      ),
    );
  }
  function education(
    index: number,
    key: keyof OnboardingDraft["education"][number],
    value: string,
  ) {
    update(
      "education",
      draft.education.map((item, i) =>
        i === index ? { ...item, [key]: value } : item,
      ),
    );
  }
  function addSkill() {
    const name = skill.trim(),
      issue = skillError(name);
    if (issue) return setSkillNotice(issue);
    if (draft.skills.some((item) => item.toLowerCase() === name.toLowerCase()))
      return setSkillNotice("That skill is already in your list.");
    if (draft.skills.length >= 50)
      return setSkillNotice("Use up to 50 skills.");
    update("skills", [...draft.skills, name]);
    setSkill("");
    setSkillNotice("");
  }
  function chooseResume(file: File | undefined) {
    setResumeError("");
    dirty.current = true;
    if (!file) return setResume(null);
    if (!file.size || file.size > MAX_RESUME_BYTES) {
      setResume(null);
      return setResumeError("Choose a non-empty text resume under 4 MB.");
    }
    if (
      !file.name.toLowerCase().endsWith(".txt") ||
      (file.type && file.type !== "text/plain")
    ) {
      setResume(null);
      return setResumeError(
        "Export your resume as UTF-8 plain text (.txt), or add your background manually.",
      );
    }
    setResume(file);
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setAttempted(true);
    setError("");
    if (step === 3 && skill.trim()) {
      setSkillNotice(
        "Add this skill to your list, or clear the field before continuing.",
      );
      return;
    }
    if (onboardingErrors(draft, step).length || (step === 3 && resumeError))
      return;
    if (step < ONBOARDING_STEPS.length - 1) {
      setStep(step + 1);
      setAttempted(false);
      return;
    }
    const invalid = ONBOARDING_STEPS.findIndex(
      (_, index) => onboardingErrors(draft, index).length > 0,
    );
    if (invalid !== -1) {
      setStep(invalid);
      return;
    }
    setBusy(true);
    try {
      await saveOnboarding(draft, resume, saveState.current, {
        saveProfile: (payload) =>
          sendWorkspaceCommand<ApiSchema["CandidateOut"]>(
            "candidate.save",
            payload,
          ),
        addSkill: (name) =>
          sendWorkspaceCommand<ApiSchema["SkillOut"]>("candidate.skill.add", {
            name,
            level: 3,
          }),
        removeSkill: (item) =>
          sendWorkspaceCommand("candidate.skill.remove", {
            id: item.id,
            name: item.name,
            expected_version: item.version,
          }),
        uploadResume: async (file, key) => {
          const body = new FormData();
          body.set("file", file);
          const response = await fetch("/api/workspace/resume", {
            method: "POST",
            headers: { "Idempotency-Key": key },
            body,
            cache: "no-store",
          });
          const payload = await response.json().catch(() => null);
          if (!response.ok)
            throw new WorkspaceError(
              response.status,
              payload?.error?.code || "RESUME_UPLOAD_FAILED",
              payload?.error?.message ||
                "Your resume upload was not confirmed. Retry to check its result.",
            );
          if (!Number.isInteger(payload?.data?.candidate_version))
            throw new WorkspaceError(
              503,
              "RESUME_UPLOAD_UNCONFIRMED",
              "Your resume upload was not confirmed. Retry to check its result.",
            );
          return payload.data;
        },
        newKey: () => crypto.randomUUID(),
        status: setSaveStatus,
      });
      dirty.current = false;
      await refresh().catch(() => undefined);
      router.push("/candidate/profile");
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to confirm this save. Please try again.",
      );
      setSaveStatus(
        saveState.current.hasSavedProfile
          ? "Your profile was saved. Some remaining items need attention; retry to finish or edit the selection."
          : "Your save has not been confirmed. Retry to check its result.",
      );
      await refresh().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  const titles = [
    "A proper introduction.",
    "What makes a role right for you?",
    "Your experience, in your words.",
    "What do you bring to the table?",
    "Make sure it feels like you.",
  ];
  const descriptions = [
    "Start with how you want to be known. Your verified account email stays connected to your sign-in.",
    "Choose the work that fits your life. Your compensation minimum stays private.",
    "Add work, projects, volunteering, and education that help explain your journey. These sections are optional.",
    "Add your strengths and, if you like, a private text resume. You can complete this without uploading a document.",
    "Review the information you choose to save. You can return and edit it at any time.",
  ];
  return (
    <Frame
      loadWarning={loadWarning}
      onRetry={() => refresh().catch(() => undefined)}
    >
      <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-16">
        <aside className="lg:sticky lg:top-8 lg:self-start">
          <p className="eyebrow mb-3">Profile</p>
          <p className="font-serif text-3xl">
            A little preparation.
            <br className="hidden lg:block" /> A better introduction.
          </p>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
            A thoughtful profile helps us understand your next chapter.
          </p>
          <ol
            className="mt-7 hidden space-y-4 lg:block"
            aria-label="Onboarding steps"
          >
            {ONBOARDING_STEPS.map((name, index) => (
              <li
                key={name}
                aria-current={step === index ? "step" : undefined}
                className="flex items-center gap-3 text-sm"
              >
                <span
                  className={`flex size-7 items-center justify-center rounded-full border ${index <= step ? "border-primary bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                >
                  {index < step ? (
                    <Check aria-hidden="true" className="size-3.5" />
                  ) : (
                    index + 1
                  )}
                </span>
                <span
                  className={
                    index === step ? "font-medium" : "text-muted-foreground"
                  }
                >
                  {name}
                </span>
              </li>
            ))}
          </ol>
          <div className="mt-8 hidden rounded-lg bg-secondary p-4 text-sm lg:block">
            <ShieldCheck className="mb-2 size-5 text-primary" />
            <p>Your pace and privacy matter.</p>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              Saving your profile does not activate it. You choose when to start
              receiving introductions.
            </p>
          </div>
        </aside>
        <form onSubmit={submit} noValidate aria-busy={busy} className="min-w-0">
          <div className="mb-7 lg:hidden">
            <Progression steps={ONBOARDING_STEPS} current={step} />
          </div>
          <p className="eyebrow mb-3" aria-live="polite">
            Step {step + 1} of {ONBOARDING_STEPS.length} ·{" "}
            {ONBOARDING_STEPS[step]}
          </p>
          <h1
            ref={heading}
            tabIndex={-1}
            className="text-4xl font-normal text-balance md:text-5xl"
          >
            {titles[step]}
          </h1>
          <p className="mt-4 max-w-2xl text-pretty text-muted-foreground">
            {descriptions[step]}
          </p>
          <p className="mt-3 text-xs text-muted-foreground">
            Changes are saved when you finish the review.
          </p>
          {(errors.length > 0 || error) && (
            <Alert variant="destructive" className="mt-6">
              <AlertDescription role="alert">
                {error && <p>{error}</p>}
                {errors.length > 0 && (
                  <ul className="list-disc pl-5">
                    {errors.map((message) => (
                      <li key={message}>{message}</li>
                    ))}
                  </ul>
                )}
              </AlertDescription>
            </Alert>
          )}
          {saveStatus && (
            <p
              role="status"
              aria-live="polite"
              className="mt-5 text-sm text-primary"
            >
              {saveStatus}
            </p>
          )}
          <fieldset disabled={busy} className="mt-9 min-w-0 space-y-9">
            {step === 0 && (
              <>
                <div className="grid gap-5 sm:grid-cols-2">
                  <TextField
                    id="display-name"
                    label="Name you go by"
                    value={draft.displayName}
                    onChange={(value) => update("displayName", value)}
                    maxLength={120}
                    autoComplete="name"
                  />
                  <Field>
                    <FieldLabel htmlFor="account-email">
                      Verified account email
                    </FieldLabel>
                    <Input
                      id="account-email"
                      type="email"
                      value={initial.session?.email || ""}
                      readOnly
                      className="bg-muted/40"
                    />
                    <FieldDescription>
                      Managed through your sign-in account.
                    </FieldDescription>
                  </Field>
                </div>
                <TextField
                  id="headline"
                  label="Professional headline"
                  value={draft.headline}
                  onChange={(value) => update("headline", value)}
                  maxLength={180}
                  placeholder="e.g. Product designer who makes complex things feel simple"
                />
                <TextField
                  id="region"
                  label="City or region"
                  value={draft.region}
                  onChange={(value) => update("region", value)}
                  maxLength={160}
                  autoComplete="address-level2"
                  help="A general location is enough; no street address needed."
                />
                <Field>
                  <FieldLabel htmlFor="professional-summary">
                    About you{" "}
                    <span className="font-normal text-muted-foreground">
                      (optional)
                    </span>
                  </FieldLabel>
                  <Textarea
                    id="professional-summary"
                    value={draft.summary}
                    rows={5}
                    maxLength={10000}
                    onChange={(event) => update("summary", event.target.value)}
                    placeholder="What have you worked on, what matters to you, and what would you like to do next?"
                  />
                  <FieldDescription>
                    {draft.summary.length.toLocaleString()} / 10,000 characters
                  </FieldDescription>
                </Field>
                <div className="grid gap-5 sm:grid-cols-2">
                  <TextField
                    id="linkedin-profile"
                    label="LinkedIn profile (optional)"
                    type="url"
                    value={draft.linkedin}
                    onChange={(value) => update("linkedin", value)}
                    maxLength={500}
                    placeholder="https://www.linkedin.com/in/you"
                    help="A profile link does not import your work history."
                  />
                  <TextField
                    id="portfolio-link"
                    label="Portfolio or website (optional)"
                    type="url"
                    value={draft.portfolio}
                    onChange={(value) => update("portfolio", value)}
                    maxLength={500}
                    placeholder="https://your-site.com"
                  />
                </div>
              </>
            )}
            {step === 1 && (
              <>
                <TextField
                  id="desired-roles"
                  label="Desired role families"
                  value={draft.roles}
                  onChange={(value) => update("roles", value)}
                  maxLength={2400}
                  placeholder="Product design, UX research"
                  help="Separate role families with commas. Add up to 20."
                />
                <ChoiceList
                  legend="Employment types"
                  options={EMPLOYMENT_OPTIONS}
                  value={draft.employmentTypes}
                  onChange={(value) => update("employmentTypes", value)}
                />
                <ChoiceList
                  legend="Work arrangements"
                  options={WORK_OPTIONS}
                  value={draft.workModes}
                  onChange={(value) => update("workModes", value)}
                />
                <TextField
                  id="preferred-locations"
                  label="Preferred work locations (optional)"
                  value={draft.locations}
                  onChange={(value) => update("locations", value)}
                  maxLength={6000}
                  placeholder="Seattle, Portland"
                  help="Separate locations with commas; include regions you could work from or relocate to."
                />
                <Section
                  title="Compensation"
                  description="Your minimum is encrypted and never shown to employers. Leave it blank if you have no minimum."
                >
                  <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_100px_130px]">
                    <TextField
                      id="minimum-compensation"
                      label="Minimum (optional)"
                      type="text"
                      value={draft.compensation}
                      onChange={(value) => update("compensation", value)}
                      maxLength={15}
                      placeholder="e.g. 85000"
                    />
                    <TextField
                      id="compensation-currency"
                      label="Currency"
                      value={draft.currency}
                      onChange={(value) =>
                        update("currency", value.toUpperCase())
                      }
                      maxLength={3}
                    />
                    <Field>
                      <FieldLabel htmlFor="compensation-period">Per</FieldLabel>
                      <select
                        id="compensation-period"
                        value={draft.payPeriod}
                        onChange={(event) =>
                          update("payPeriod", event.target.value)
                        }
                        className="h-10 rounded-lg border bg-background px-3 text-sm"
                      >
                        <option value="ANNUAL">Year</option>
                        <option value="MONTHLY">Month</option>
                        <option value="HOURLY">Hour</option>
                      </select>
                    </Field>
                  </div>
                </Section>
                <Section
                  title="Timing & pace"
                  description="Availability dates are optional. Your decision limit controls how many opportunities can await your response at once."
                >
                  <div className="grid gap-5 sm:grid-cols-2">
                    <TextField
                      id="available-from"
                      label="Available from (optional)"
                      type="date"
                      value={draft.availableFrom}
                      onChange={(value) => update("availableFrom", value)}
                    />
                    <TextField
                      id="available-until"
                      label="Available until (optional)"
                      type="date"
                      value={draft.availableUntil}
                      onChange={(value) => update("availableUntil", value)}
                    />
                  </div>
                  <Field>
                    <FieldLabel htmlFor="decision-capacity">
                      Active decision limit
                    </FieldLabel>
                    <select
                      id="decision-capacity"
                      value={draft.capacity}
                      onChange={(event) =>
                        update("capacity", Number(event.target.value))
                      }
                      className="h-10 w-48 rounded-lg border bg-background px-3 text-sm"
                    >
                      {Array.from({ length: 10 }, (_, index) => index + 1).map(
                        (value) => (
                          <option key={value} value={value}>
                            {value}{" "}
                            {value === 1 ? "opportunity" : "opportunities"}
                          </option>
                        ),
                      )}
                    </select>
                  </Field>
                </Section>
              </>
            )}
            {step === 2 && (
              <>
                <Section
                  title="Experience"
                  description="Paid work, projects, volunteering, and independent work all count."
                >
                  {draft.experiences.length === 0 && (
                    <p className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
                      Starting out or changing direction? You can leave this
                      empty.
                    </p>
                  )}
                  {draft.experiences.map((item, index) => (
                    <article key={index} className="panel space-y-5 p-5">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium">
                          Experience {index + 1}
                        </h3>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            update(
                              "experiences",
                              draft.experiences.filter((_, i) => i !== index),
                            )
                          }
                          aria-label={`Remove experience ${index + 1}`}
                        >
                          <X className="size-4" />
                          Remove
                        </Button>
                      </div>
                      <div className="grid gap-5 sm:grid-cols-2">
                        <TextField
                          id={`experience-title-${index}`}
                          label="Role or project title"
                          value={item.title}
                          onChange={(value) =>
                            experience(index, "title", value)
                          }
                          maxLength={180}
                        />
                        <TextField
                          id={`experience-org-${index}`}
                          label="Organization or project"
                          value={item.organization_label}
                          onChange={(value) =>
                            experience(index, "organization_label", value)
                          }
                          maxLength={180}
                        />
                      </div>
                      <div className="grid gap-5 sm:grid-cols-2">
                        <TextField
                          id={`experience-start-${index}`}
                          label="Start date"
                          type="date"
                          value={item.start_date}
                          onChange={(value) =>
                            experience(index, "start_date", value)
                          }
                        />
                        <TextField
                          id={`experience-end-${index}`}
                          label="End date (blank if current)"
                          type="date"
                          value={item.end_date}
                          onChange={(value) =>
                            experience(index, "end_date", value)
                          }
                        />
                      </div>
                      <Field>
                        <FieldLabel htmlFor={`experience-details-${index}`}>
                          What did you do? (optional)
                        </FieldLabel>
                        <Textarea
                          id={`experience-details-${index}`}
                          rows={3}
                          value={item.details}
                          maxLength={3000}
                          onChange={(event) =>
                            experience(index, "details", event.target.value)
                          }
                        />
                      </Field>
                      <label className="flex items-start gap-3 text-sm">
                        <input
                          className="mt-1 size-4 accent-primary"
                          type="checkbox"
                          checked={item.disclose_organization}
                          onChange={(event) =>
                            experience(
                              index,
                              "disclose_organization",
                              event.target.checked,
                            )
                          }
                        />
                        <span>
                          Show this organization’s name when my experience is
                          shared. Leave unchecked to keep the name private.
                        </span>
                      </label>
                    </article>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    className="self-start"
                    disabled={draft.experiences.length >= 50}
                    onClick={() =>
                      update("experiences", [
                        ...draft.experiences,
                        emptyExperience(),
                      ])
                    }
                  >
                    <Plus className="size-4" />
                    Add experience
                  </Button>
                </Section>
                <Section
                  title="Education & qualifications"
                  description="Include degrees, training programs, or professional qualifications."
                >
                  {draft.education.map((item, index) => (
                    <article key={index} className="panel space-y-5 p-5">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium">
                          Education {index + 1}
                        </h3>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            update(
                              "education",
                              draft.education.filter((_, i) => i !== index),
                            )
                          }
                          aria-label={`Remove education ${index + 1}`}
                        >
                          <X className="size-4" />
                          Remove
                        </Button>
                      </div>
                      <TextField
                        id={`education-title-${index}`}
                        label="Qualification or program"
                        value={item.qualification}
                        onChange={(value) =>
                          education(index, "qualification", value)
                        }
                        maxLength={180}
                      />
                      <TextField
                        id={`education-institution-${index}`}
                        label="Institution"
                        value={item.institution}
                        onChange={(value) =>
                          education(index, "institution", value)
                        }
                        maxLength={180}
                      />
                      <Field>
                        <FieldLabel htmlFor={`education-details-${index}`}>
                          Relevant details (optional)
                        </FieldLabel>
                        <Textarea
                          id={`education-details-${index}`}
                          rows={3}
                          maxLength={2000}
                          value={item.details}
                          onChange={(event) =>
                            education(index, "details", event.target.value)
                          }
                        />
                      </Field>
                    </article>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    className="self-start"
                    disabled={draft.education.length >= 30}
                    onClick={() =>
                      update("education", [
                        ...draft.education,
                        emptyEducation(),
                      ])
                    }
                  >
                    <Plus className="size-4" />
                    Add education
                  </Button>
                </Section>
              </>
            )}
            {step === 3 && (
              <>
                <Section
                  title="Your skills"
                  description="These are self-reported; verified evidence is handled separately. Add up to 50."
                >
                  <div className="flex gap-2">
                    <Input
                      id="new-skill"
                      aria-label="New skill"
                      value={skill}
                      maxLength={100}
                      placeholder="e.g. Python, facilitation, project management"
                      onChange={(event) => setSkill(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addSkill();
                        }
                      }}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={addSkill}
                      disabled={!skill.trim()}
                    >
                      <Plus className="size-4" />
                      Add
                    </Button>
                  </div>
                  {skillNotice && (
                    <p role="alert" className="text-sm text-destructive">
                      {skillNotice}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {draft.skills.map((name) => (
                      <Badge
                        key={name.toLowerCase()}
                        variant="secondary"
                        className="gap-2 py-2 pl-3 pr-1"
                      >
                        {name}
                        <button
                          type="button"
                          className="rounded-full p-1 hover:bg-background"
                          aria-label={`Remove skill ${name}`}
                          onClick={() =>
                            update(
                              "skills",
                              draft.skills.filter((item) => item !== name),
                            )
                          }
                        >
                          <X className="size-3.5" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                  {!draft.skills.length && (
                    <p className="text-sm text-muted-foreground">
                      No skills added yet. You can add them later.
                    </p>
                  )}
                </Section>
                <Section
                  title="Private resume (optional)"
                  description="Upload a UTF-8 plain text (.txt) resume under 4 MB. You can export text from your document editor, or use the background section instead."
                >
                  <div className="rounded-xl border border-dashed bg-muted/20 p-5">
                    <FileText
                      aria-hidden="true"
                      className="mb-3 size-6 text-primary"
                    />
                    <Field>
                      <FieldLabel htmlFor="resume-file">
                        Choose a text resume
                      </FieldLabel>
                      <Input
                        id="resume-file"
                        type="file"
                        accept=".txt,text/plain"
                        onChange={(event) =>
                          chooseResume(event.target.files?.[0])
                        }
                        aria-describedby="resume-privacy"
                      />
                      <FieldDescription id="resume-privacy">
                        Your resume is encrypted and stored privately. Uploading
                        does not share it with employers or automatically change
                        your profile.
                      </FieldDescription>
                    </Field>
                    {resume && (
                      <div className="mt-4 flex items-center justify-between gap-3 text-sm">
                        <span className="break-all">
                          {resume.name} · {(resume.size / 1000).toFixed(0)} KB
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            chooseResume(undefined);
                            const input = document.getElementById(
                              "resume-file",
                            ) as HTMLInputElement | null;
                            if (input) input.value = "";
                          }}
                        >
                          Remove
                        </Button>
                      </div>
                    )}
                    {resumeError && (
                      <p role="alert" className="mt-3 text-sm text-destructive">
                        {resumeError}
                      </p>
                    )}
                  </div>
                </Section>
              </>
            )}
            {step === 4 && (
              <>
                <div className="panel divide-y">
                  {[
                    [
                      "About you",
                      `${draft.displayName} · ${draft.headline}`,
                      `${draft.region}${draft.summary ? `\n${draft.summary}` : ""}`,
                      0,
                    ],
                    [
                      "Professional links",
                      [draft.linkedin, draft.portfolio]
                        .filter(Boolean)
                        .join("\n") || "No links added",
                      "",
                      0,
                    ],
                    [
                      "Looking for",
                      labels(draft.roles).join(", "),
                      `${EMPLOYMENT_OPTIONS.filter(([id]) =>
                        draft.employmentTypes.includes(id),
                      )
                        .map(([, label]) => label)
                        .join(", ")} · ${WORK_OPTIONS.filter(([id]) =>
                        draft.workModes.includes(id),
                      )
                        .map(([, label]) => label)
                        .join(
                          ", ",
                        )}${draft.locations ? `\nPreferred locations: ${labels(draft.locations).join(", ")}` : ""}`,
                      1,
                    ],
                    [
                      "Compensation & timing",
                      draft.compensation
                        ? `${draft.compensation} ${draft.currency} / ${draft.payPeriod.toLowerCase()} · private minimum`
                        : "No compensation minimum",
                      `${draft.availableFrom ? `Available from ${draft.availableFrom}` : "No start date set"}${draft.availableUntil ? ` until ${draft.availableUntil}` : ""}\nUp to ${draft.capacity} active decisions`,
                      1,
                    ],
                    [
                      "Background",
                      `${draft.experiences.length} experience ${draft.experiences.length === 1 ? "entry" : "entries"} · ${draft.education.length} education ${draft.education.length === 1 ? "entry" : "entries"}`,
                      [
                        ...draft.experiences.map(
                          (item) =>
                            `${item.title} at ${item.organization_label} · ${item.start_date} – ${item.end_date || "present"}${item.disclose_organization ? "" : " · organization name private"}`,
                        ),
                        ...draft.education.map(
                          (item) =>
                            `${item.qualification} · ${item.institution}`,
                        ),
                      ].join("\n"),
                      2,
                    ],
                    [
                      "Skills & resume",
                      draft.skills.join(", ") || "No skills added",
                      resume
                        ? `Private text resume: ${resume.name}`
                        : "No new resume selected",
                      3,
                    ],
                  ].map(([label, value, detail, index]) => (
                    <div
                      key={String(label)}
                      className="flex items-start justify-between gap-4 p-5"
                    >
                      <div className="min-w-0">
                        <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                          {label}
                        </h2>
                        <p className="mt-2 whitespace-pre-wrap break-words text-sm">
                          {value}
                        </p>
                        {detail && (
                          <p className="mt-2 whitespace-pre-wrap break-words text-sm text-muted-foreground">
                            {detail}
                          </p>
                        )}
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Edit ${label}`}
                        onClick={() => {
                          setStep(Number(index));
                          setAttempted(false);
                        }}
                      >
                        Edit
                      </Button>
                    </div>
                  ))}
                </div>
                <div className="space-y-5 rounded-xl border bg-secondary/40 p-5">
                  <h2 className="flex items-center gap-2 text-lg">
                    <ShieldCheck className="size-5" />
                    Your choices
                  </h2>
                  <label className="flex items-start gap-3 text-sm leading-relaxed">
                    <input
                      className="mt-1 size-4 shrink-0 accent-primary"
                      type="checkbox"
                      checked={draft.termsAccepted}
                      onChange={(event) =>
                        update("termsAccepted", event.target.checked)
                      }
                    />
                    <span>
                      I accept that introductions require both parties’
                      interest, offers require a separate response, and
                      employment starts require independent verification.
                    </span>
                  </label>
                  <label className="flex items-start gap-3 text-sm leading-relaxed">
                    <input
                      className="mt-1 size-4 shrink-0 accent-primary"
                      type="checkbox"
                      checked={draft.privacyAccepted}
                      onChange={(event) =>
                        update("privacyAccepted", event.target.checked)
                      }
                    />
                    <span>
                      I consent to storing and processing the career information
                      I have chosen to provide for introductions. My
                      compensation minimum stays private; evidence sharing
                      requires separate, revocable consent.
                    </span>
                  </label>
                  <label className="flex items-start gap-3 text-sm leading-relaxed">
                    <input
                      className="mt-1 size-4 shrink-0 accent-primary"
                      type="checkbox"
                      checked={draft.profileConfirmed}
                      onChange={(event) =>
                        update("profileConfirmed", event.target.checked)
                      }
                    />
                    <span>
                      I have reviewed this profile and confirm that the
                      information is accurate. I can edit it and manage my data
                      in Privacy & consent.
                    </span>
                  </label>
                </div>
                <p className="text-sm text-muted-foreground">
                  Your profile is saved in its current visibility state. A new
                  profile starts as a draft; activate it from your profile page
                  when you are ready.
                </p>
              </>
            )}
          </fieldset>
          <div className="mt-10 flex items-center justify-between gap-4 border-t pt-6">
            <Button
              type="button"
              variant="ghost"
              disabled={busy || step === 0}
              onClick={() => {
                setStep(step - 1);
                setAttempted(false);
                setError("");
              }}
            >
              <ArrowLeft className="size-4" />
              Back
            </Button>
            <Button type="submit" size="lg" disabled={busy}>
              {busy ? (
                <>
                  <LoaderCircle className="size-4 animate-spin" />
                  Saving…
                </>
              ) : step === ONBOARDING_STEPS.length - 1 ? (
                <>
                  Save my profile
                  <Check className="size-4" />
                </>
              ) : (
                <>
                  Continue
                  <ArrowRight className="size-4" />
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </Frame>
  );
}
