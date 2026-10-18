"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSWRConfig } from "swr";
import { ArrowLeft, ArrowRight, Building2, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Brand } from "@/components/brand";
import { Progression } from "@/components/workspace/kit";
import { useWorkspace } from "@/lib/workspace";
import type { Role } from "@/lib/contracts";
import { cn } from "@/lib/utils";

function EntryFrame({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh flex-col">
      <header className="page-width flex min-h-20 flex-wrap items-center justify-between gap-3 py-4">
        <Brand />
        <Badge variant="outline">Career Kitchen</Badge>
      </header>
      <div className="flex flex-1 items-center justify-center px-6 pt-10 pb-28 sm:pb-16">
        {children}
      </div>
    </main>
  );
}

function RolePicker({
  value,
  onChange,
}: {
  value: Role;
  onChange: (r: Role) => void;
}) {
  const options = [
    {
      id: "candidate" as const,
      label: "I’m looking for a role",
      icon: UserRound,
    },
    { id: "employer" as const, label: "I’m hiring", icon: Building2 },
  ];
  return (
    <fieldset>
      <legend className="mb-3 text-sm font-medium">
        Choose your workspace
      </legend>
      <div className="grid grid-cols-2 gap-3">
        {options.map(({ id, label, icon: Icon }) => (
          <label key={id} className="cursor-pointer">
            <input
              type="radio"
              name="workspace-role"
              value={id}
              checked={value === id}
              onChange={() => onChange(id)}
              className="peer sr-only"
            />
            <span
              className={cn(
                "flex h-full flex-col items-start gap-3 rounded-md border p-4 text-left text-sm transition-colors hover:bg-muted peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring",
                value === id && "border-primary bg-secondary",
              )}
            >
              <Icon
                aria-hidden="true"
                className={cn(
                  "size-5",
                  value === id ? "text-primary" : "text-muted-foreground",
                )}
              />
              {label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function AuthForm({ mode }: { mode: "sign-in" | "get-started" }) {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const [role, setRole] = useState<Role>("candidate");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [account, setAccount] = useState("candidate-01");
  const [authMode, setAuthMode] = useState<
    "local" | "supabase" | "unconfigured" | null
  >(null);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const signUp = mode === "get-started";
  const emailError = !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  const passwordError = password.length < 8;

  useEffect(() => {
    const requestedRole = new URLSearchParams(window.location.search).get(
      "role",
    );
    if (requestedRole === "candidate" || requestedRole === "employer")
      setRole(requestedRole);
    const controller = new AbortController();
    fetch("/api/auth/config", { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Unable to load sign-in configuration.");
        const configuration = await response.json();
        setAuthMode(configuration.mode);
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "Unable to load sign-in configuration.",
          );
      });
    return () => controller.abort();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    setError("");
    setNotice("");
    if (
      !authMode ||
      authMode === "unconfigured" ||
      busy ||
      (authMode === "supabase" && (emailError || passwordError))
    )
      return;
    setBusy(true);
    try {
      const response = await fetch("/api/auth/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          authMode === "local"
            ? { account: role === "employer" ? "employer" : account, role }
            : { email: email.trim(), password, mode, role },
        ),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.error === "string"
            ? result.error
            : result.error?.message || "Unable to sign in. Please try again.",
        );
      if (result.needsEmailConfirmation) {
        setNotice(
          "Check your email to confirm your account, then return to sign in.",
        );
        setPassword("");
        return;
      }
      await mutate(
        (key) => typeof key === "string" && key.startsWith("/api/workspace"),
        undefined,
        { revalidate: false },
      );
      router.push(
        result.redirectTo ||
          (signUp && role === "candidate"
            ? "/onboarding/candidate"
            : `/${role}`),
      );
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <EntryFrame>
      <form
        onSubmit={submit}
        className="rise flex w-full max-w-md flex-col gap-7"
        aria-busy={busy}
        noValidate
      >
        <div>
          <p className="eyebrow mb-3">Your place at the table</p>
          <h1 className="text-4xl font-normal text-balance">
            {signUp
              ? "Begin with what matters to you."
              : "Welcome back to the kitchen."}
          </h1>
          <p className="mt-3 text-muted-foreground">
            {signUp
              ? "A more thoughtful way to find your next role or teammate."
              : "Sign in to continue where you left off."}
          </p>
        </div>
        <RolePicker value={role} onChange={setRole} />
        {authMode === "local" ? (
          <>
            <Alert>
              <AlertDescription>
                Local development uses seeded test accounts. Changes are saved
                to the backend database.
              </AlertDescription>
            </Alert>
            {role === "candidate" && (
              <Field>
                <FieldLabel htmlFor="account">Test candidate</FieldLabel>
                <select
                  id="account"
                  className="h-10 rounded-lg border bg-background px-3 text-sm"
                  value={account}
                  onChange={(event) => setAccount(event.target.value)}
                >
                  {Array.from({ length: 30 }, (_, index) => {
                    const id = `candidate-${String(index + 1).padStart(2, "0")}`;
                    return (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    );
                  })}
                </select>
              </Field>
            )}
          </>
        ) : authMode === "supabase" ? (
          <FieldGroup>
            <Field data-invalid={submitted && emailError}>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                aria-invalid={submitted && emailError}
                onChange={(event) => setEmail(event.target.value)}
              />
              {submitted && emailError && (
                <FieldError>Enter a valid email address.</FieldError>
              )}
            </Field>
            <Field data-invalid={submitted && passwordError}>
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Input
                id="password"
                type="password"
                autoComplete={signUp ? "new-password" : "current-password"}
                value={password}
                aria-invalid={submitted && passwordError}
                onChange={(event) => setPassword(event.target.value)}
              />
              {submitted && passwordError ? (
                <FieldError>Use at least 8 characters.</FieldError>
              ) : (
                signUp && (
                  <FieldDescription>At least 8 characters.</FieldDescription>
                )
              )}
            </Field>
          </FieldGroup>
        ) : (
          <Alert>
            <AlertDescription>
              {authMode === null
                ? "Loading sign-in configuration…"
                : "Authentication is not configured. Configure Supabase or enable local development authentication on the server."}
            </AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription role="alert">{error}</AlertDescription>
          </Alert>
        )}
        {notice && (
          <Alert>
            <AlertDescription role="status">{notice}</AlertDescription>
          </Alert>
        )}
        <Button
          type="submit"
          size="lg"
          disabled={busy || !authMode || authMode === "unconfigured"}
        >
          {busy
            ? "Signing in…"
            : authMode === "local"
              ? "Open test workspace"
              : signUp
                ? "Create account"
                : "Sign in"}
          <ArrowRight aria-hidden="true" data-icon="inline-end" />
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          {signUp ? "Already have an account? " : "New to Career Kitchen? "}
          <Link
            className="text-primary underline-offset-4 hover:underline"
            href={`${signUp ? "/sign-in" : "/get-started"}?role=${role}`}
          >
            {signUp ? "Sign in" : "Get started"}
          </Link>
        </p>
      </form>
    </EntryFrame>
  );
}

const STEPS = ["Role", "Must-haves", "Capacity & consent"] as const;

export function CandidateOnboarding() {
  const router = useRouter();
  const { data, execute, isLoading, error } = useWorkspace();
  const [step, setStep] = useState(0);
  const [title, setTitle] = useState<string | null>(null);
  const [region, setRegion] = useState<string | null>(null);
  const [roleFamily, setRoleFamily] = useState<string | null>(null);
  const [remote, setRemote] = useState<string | null>(null);
  const [draftCompensation, setCompensation] = useState<string | null>(null);
  const [draftCurrency, setCurrency] = useState<string | null>(null);
  const [draftEmploymentType, setEmploymentType] = useState<string | null>(
    null,
  );
  const [draftPayPeriod, setPayPeriod] = useState<string | null>(null);
  const [capacity, setCapacity] = useState<string | null>(null);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const [profileConfirmed, setProfileConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const previousStep = useRef(step);

  useEffect(() => {
    if (step !== previousStep.current) headingRef.current?.focus();
    previousStep.current = step;
  }, [step]);
  const headline = title ?? data.profile.title;
  const location = region ?? data.profile.location;
  const family = roleFamily ?? data.profile.roles?.[0] ?? "";
  const storedWorkModes = data.backend.candidate?.work_modes;
  const arrangement =
    remote ??
    (storedWorkModes?.length === 2 &&
    storedWorkModes.includes("REMOTE") &&
    storedWorkModes.includes("HYBRID")
      ? "Remote or hybrid"
      : storedWorkModes?.length === 1 && storedWorkModes[0] === "ONSITE"
        ? "On-site"
        : data.profile.remote);
  const cap = capacity ?? String(data.profile.capacity);
  const compensation =
    draftCompensation ?? data.backend.candidate?.compensation_floor ?? "";
  const currency = draftCurrency ?? data.backend.candidate?.currency ?? "USD";
  const employmentType =
    draftEmploymentType ??
    data.backend.candidate?.employment_types[0] ??
    "FULL_TIME";
  const payPeriod =
    draftPayPeriod ?? data.backend.candidate?.compensation_period ?? "ANNUAL";
  const titleError =
    headline.trim().length < 3 ||
    headline.length > 180 ||
    location.trim().length < 2 ||
    family.trim().length < 2;
  const compensationError =
    compensation !== "" &&
    (!Number.isFinite(Number(compensation)) ||
      Number(compensation) < 0 ||
      !/^\d+(\.\d{1,2})?$/.test(compensation));
  const currencyError = !/^[A-Z]{3}$/.test(currency);
  const consentError = !termsAccepted || !privacyAccepted || !profileConfirmed;

  async function next(event: React.FormEvent) {
    event.preventDefault();
    if (
      busy ||
      isLoading ||
      error ||
      (step === 0 && titleError) ||
      (step === 1 && (compensationError || currencyError))
    )
      return;
    if (step < STEPS.length - 1) return setStep(step + 1);
    if (consentError) return;
    setBusy(true);
    const saved = await execute(
      "candidate.save",
      {
        expected_version: data.profile.version ?? 0,
        headline: headline.trim(),
        summary: data.profile.summary,
        region: location.trim(),
        role_families:
          roleFamily === null && data.backend.candidate
            ? data.backend.candidate.role_families
            : [family.trim()],
        employment_types:
          draftEmploymentType === null && data.backend.candidate
            ? data.backend.candidate.employment_types
            : [employmentType],
        work_modes:
          remote === null && data.backend.candidate
            ? data.backend.candidate.work_modes
            : arrangement === "Remote or hybrid"
              ? ["REMOTE", "HYBRID"]
              : arrangement === "On-site"
                ? ["ONSITE"]
                : arrangement === "Hybrid"
                  ? ["HYBRID"]
                  : ["REMOTE"],
        locations:
          region === null && data.backend.candidate
            ? data.backend.candidate.locations
            : [location.trim()],
        compensation_floor: compensation === "" ? null : compensation,
        currency,
        compensation_period: payPeriod,
        cap: Number(cap),
        experiences: data.backend.candidate?.experiences ?? [],
        education: data.backend.candidate?.education ?? [],
        available_from: data.backend.candidate?.available_from ?? null,
        available_until: data.backend.candidate?.available_until ?? null,
        terms_accepted: termsAccepted,
        privacy_accepted: privacyAccepted,
        profile_confirmed: profileConfirmed,
      },
      "Your profile and preferences are saved.",
    );
    setBusy(false);
    if (saved) router.push("/candidate/profile");
  }

  return (
    <EntryFrame>
      <form
        onSubmit={next}
        className="rise flex w-full max-w-lg flex-col gap-7"
        aria-busy={busy}
        noValidate
      >
        <Progression steps={STEPS} current={step} />
        <p className="eyebrow" aria-live="polite">
          Step {step + 1} of {STEPS.length} · {STEPS[step]}
        </p>
        {error && (
          <Alert variant="destructive">
            <AlertDescription role="alert">
              {error instanceof Error
                ? error.message
                : "Unable to load your profile."}
            </AlertDescription>
          </Alert>
        )}
        {step === 0 && (
          <section className="flex flex-col gap-6">
            <h1
              ref={headingRef}
              tabIndex={-1}
              className="text-3xl font-normal text-balance"
            >
              What would you like to do next?
            </h1>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="title">Role you’re looking for</FieldLabel>
                <Input
                  id="title"
                  value={headline}
                  maxLength={180}
                  onChange={(event) => setTitle(event.target.value)}
                />
                <FieldDescription>
                  Between 3 and 180 characters.
                </FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="region">Region</FieldLabel>
                <Input
                  id="region"
                  value={location}
                  maxLength={160}
                  onChange={(event) => setRegion(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="role-family">Role family</FieldLabel>
                <Input
                  id="role-family"
                  placeholder="For example: Software Engineering"
                  maxLength={120}
                  value={family}
                  onChange={(event) => setRoleFamily(event.target.value)}
                />
                <FieldDescription>
                  Used to match the type of work you want.
                </FieldDescription>
              </Field>
            </FieldGroup>
          </section>
        )}
        {step === 1 && (
          <section className="flex flex-col gap-6">
            <h1
              ref={headingRef}
              tabIndex={-1}
              className="text-3xl font-normal text-balance"
            >
              Your non-negotiables
            </h1>
            <p className="-mt-3 text-muted-foreground">
              These preferences guide introductions. Compensation stays private.
            </p>
            <FieldGroup>
              <Field>
                <FieldLabel>Work arrangement</FieldLabel>
                <ToggleGroup
                  type="single"
                  variant="outline"
                  className="flex-wrap"
                  value={arrangement}
                  onValueChange={(value) => value && setRemote(value)}
                  aria-label="Work arrangement"
                >
                  {["Remote", "Remote or hybrid", "Hybrid", "On-site"].map(
                    (value) => (
                      <ToggleGroupItem key={value} value={value}>
                        {value}
                      </ToggleGroupItem>
                    ),
                  )}
                </ToggleGroup>
              </Field>
              <Field>
                <FieldLabel htmlFor="employment-type">
                  Employment type
                </FieldLabel>
                <select
                  id="employment-type"
                  className="h-10 rounded-lg border bg-background px-3 text-sm"
                  value={employmentType}
                  onChange={(event) => setEmploymentType(event.target.value)}
                >
                  {[
                    ["FULL_TIME", "Full time"],
                    ["PART_TIME", "Part time"],
                    ["CONTRACT", "Contract"],
                    ["INTERNSHIP", "Internship"],
                    ["TEMPORARY", "Temporary"],
                  ].map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field data-invalid={compensationError}>
                <FieldLabel htmlFor="comp">
                  Minimum compensation (optional)
                </FieldLabel>
                <Input
                  id="comp"
                  type="number"
                  min="0"
                  step="0.01"
                  value={compensation}
                  onChange={(event) => setCompensation(event.target.value)}
                />
                <FieldDescription>
                  Never shown to employers. Leave blank if you have no minimum.
                </FieldDescription>
                {compensationError && (
                  <FieldError>
                    Enter a nonnegative amount with at most two decimal places.
                  </FieldError>
                )}
              </Field>
              <Field>
                <FieldLabel htmlFor="pay-period">
                  Compensation period
                </FieldLabel>
                <select
                  id="pay-period"
                  className="h-10 rounded-lg border bg-background px-3 text-sm"
                  value={payPeriod}
                  onChange={(event) => setPayPeriod(event.target.value)}
                >
                  {[
                    ["ANNUAL", "Annual"],
                    ["MONTHLY", "Monthly"],
                    ["HOURLY", "Hourly"],
                  ].map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field data-invalid={currencyError}>
                <FieldLabel htmlFor="currency">Currency</FieldLabel>
                <Input
                  id="currency"
                  value={currency}
                  maxLength={3}
                  onChange={(event) =>
                    setCurrency(event.target.value.toUpperCase())
                  }
                />
                {currencyError && (
                  <FieldError>
                    Use a three-letter currency code, such as USD.
                  </FieldError>
                )}
              </Field>
            </FieldGroup>
          </section>
        )}
        {step === 2 && (
          <section className="flex flex-col gap-6">
            <h1
              ref={headingRef}
              tabIndex={-1}
              className="text-3xl font-normal text-balance"
            >
              Your pace, your choice
            </h1>
            <p className="-mt-3 text-muted-foreground">
              Choose how many opportunities can await your decision at once. You
              can activate your profile after saving it.
            </p>
            <ToggleGroup
              type="single"
              variant="outline"
              className="flex-wrap"
              value={cap}
              onValueChange={(value) => value && setCapacity(value)}
              aria-label="Active decision capacity"
            >
              {Array.from({ length: 10 }, (_, index) => String(index + 1)).map(
                (number) => (
                  <ToggleGroupItem
                    key={number}
                    value={number}
                    aria-label={`${number} active ${number === "1" ? "opportunity" : "opportunities"}`}
                    className="w-10"
                  >
                    {number}
                  </ToggleGroupItem>
                ),
              )}
            </ToggleGroup>
            <p className="text-sm font-medium text-primary">
              Your limit: {cap} active{" "}
              {cap === "1" ? "opportunity" : "opportunities"}
            </p>
            <label className="flex items-start gap-3 text-sm">
              <Checkbox
                checked={termsAccepted}
                onCheckedChange={(value) => setTermsAccepted(value === true)}
              />
              <span>
                I accept that introductions require both parties’ interest,
                offers require a separate response, and employment starts
                require independent verification.
              </span>
            </label>
            <label className="flex items-start gap-3 text-sm">
              <Checkbox
                checked={privacyAccepted}
                onCheckedChange={(value) => setPrivacyAccepted(value === true)}
              />
              <span>
                I consent to storing and processing my profile for
                introductions. My compensation minimum stays private, and
                evidence sharing requires separate consent that I can revoke.
              </span>
            </label>
            <label className="flex items-start gap-3 text-sm">
              <Checkbox
                checked={profileConfirmed}
                onCheckedChange={(value) => setProfileConfirmed(value === true)}
              />
              <span>
                I confirm that my profile and preferences are accurate.
              </span>
            </label>
          </section>
        )}
        <div className="flex justify-between gap-3">
          <Button
            type="button"
            variant="ghost"
            disabled={step === 0 || busy}
            onClick={() => setStep(step - 1)}
          >
            <ArrowLeft aria-hidden="true" data-icon="inline-start" />
            Back
          </Button>
          <Button
            type="submit"
            disabled={
              busy ||
              isLoading ||
              !!error ||
              (step === 0 && titleError) ||
              (step === 1 && (compensationError || currencyError)) ||
              (step === 2 && consentError)
            }
          >
            {busy
              ? "Saving…"
              : step === STEPS.length - 1
                ? "Save profile"
                : "Continue"}
            <ArrowRight aria-hidden="true" data-icon="inline-end" />
          </Button>
        </div>
      </form>
    </EntryFrame>
  );
}
