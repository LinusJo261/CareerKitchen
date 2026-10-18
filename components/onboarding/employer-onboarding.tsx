"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  LoaderCircle,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Progression } from "@/components/workspace/kit";
import { sendWorkspaceCommand, useWorkspace } from "@/lib/workspace";

export function EmployerOnboarding() {
  const router = useRouter();
  const { data, error, isLoading, refresh } = useWorkspace();
  const [step, setStep] = useState(0);
  const [legalName, setLegalName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [domain, setDomain] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (step) heading.current?.focus();
  }, [step]);
  const invalid =
    legalName.trim().length < 3 ||
    legalName.length > 200 ||
    displayName.trim().length < 2 ||
    displayName.length > 120 ||
    !/^[a-z0-9.-]+\.[a-z]{2,}$/.test(domain) ||
    domain.length > 200 ||
    domain.includes("..");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setAttempted(true);
    setSaveError("");
    if (invalid || busy || error || !data.session) return;
    if (!step) {
      setStep(1);
      setAttempted(false);
      return;
    }
    if (!confirmed) return;
    setBusy(true);
    try {
      await sendWorkspaceCommand("organization.create", {
        legal_name: legalName.trim(),
        display_name: displayName.trim(),
        domain,
      });
      await refresh().catch(() => undefined);
      router.push("/employer/organization");
      router.refresh();
    } catch (cause) {
      setSaveError(
        cause instanceof Error
          ? cause.message
          : "Your organization submission was not confirmed. Please retry.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="min-h-dvh">
      <header className="page-width flex min-h-20 items-center justify-between gap-3 py-4">
        <Brand />
        <Badge variant="outline">Hiring workspace</Badge>
      </header>
      <div className="page-width py-10 pb-24">
        <div className="mx-auto max-w-2xl">
          {isLoading && !data.session ? (
            <p role="status" className="flex items-center gap-3">
              <LoaderCircle className="size-5 animate-spin" />
              Loading your account…
            </p>
          ) : error || !data.session ? (
            <>
              <h1 className="text-3xl">Sign in to set up your organization.</h1>
              <p role="alert" className="mt-4 text-muted-foreground">
                {error?.message ||
                  "Your account is needed to securely save this setup."}
              </p>
              <Button className="mt-6" asChild>
                <Link href="/sign-in?role=employer">Sign in</Link>
              </Button>
            </>
          ) : data.backend.organizations.length ? (
            <>
              <p className="eyebrow mb-3">Your hiring workspace</p>
              <h1 className="text-4xl">Your organization is on the table.</h1>
              <p className="mt-4 text-muted-foreground">
                Continue to review your organization, verification status, team,
                and hiring setup.
              </p>
              <div className="panel mt-7 divide-y">
                {data.backend.organizations.map((org) => (
                  <div
                    key={org.id}
                    className="flex items-center justify-between gap-4 p-5"
                  >
                    <div>
                      <p className="font-medium">{org.display_name}</p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {org.domain}
                      </p>
                    </div>
                    <Badge variant="outline">
                      {org.verification_state.replaceAll("_", " ")}
                    </Badge>
                  </div>
                ))}
              </div>
              <Button className="mt-7" asChild>
                <Link href="/employer/organization">
                  Continue to organization
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </>
          ) : (
            <form onSubmit={submit} noValidate aria-busy={busy}>
              <Progression
                steps={["Organization", "Review & submit"]}
                current={step}
              />
              <p className="eyebrow mt-8 mb-3">Step {step + 1} of 2</p>
              <h1 ref={heading} tabIndex={-1} className="text-4xl md:text-5xl">
                {step ? "A clear start to hiring." : "Who are you hiring with?"}
              </h1>
              <p className="mt-4 text-muted-foreground">
                {step
                  ? "Review the organization you are submitting. Independent verification comes before approved hiring access."
                  : "Tell us about your organization. These details are saved when you submit the review."}
              </p>
              {(saveError ||
                (attempted && (invalid || (step === 1 && !confirmed)))) && (
                <Alert variant="destructive" className="mt-6">
                  <AlertDescription role="alert">
                    {saveError ||
                      (invalid
                        ? "Enter a legal name of 3–200 characters, a display name of 2–120 characters, and a lowercase company domain such as company.com."
                        : "Review and confirm the organization details before submitting.")}
                  </AlertDescription>
                </Alert>
              )}
              <fieldset disabled={busy} className="mt-8 space-y-6">
                {!step ? (
                  <>
                    <Field>
                      <FieldLabel htmlFor="org-legal-name">
                        Legal organization name
                      </FieldLabel>
                      <Input
                        id="org-legal-name"
                        value={legalName}
                        maxLength={200}
                        autoComplete="organization"
                        onChange={(event) => {
                          setLegalName(event.target.value);
                          setConfirmed(false);
                        }}
                      />
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="org-display-name">
                        Public display name
                      </FieldLabel>
                      <Input
                        id="org-display-name"
                        value={displayName}
                        maxLength={120}
                        onChange={(event) => {
                          setDisplayName(event.target.value);
                          setConfirmed(false);
                        }}
                      />
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="org-domain">
                        Organization domain
                      </FieldLabel>
                      <Input
                        id="org-domain"
                        value={domain}
                        maxLength={200}
                        placeholder="company.com"
                        onChange={(event) => {
                          setDomain(event.target.value.trim().toLowerCase());
                          setConfirmed(false);
                        }}
                      />
                      <FieldDescription>
                        Use the domain only, without https:// or a page path. If
                        your organization already exists, request membership
                        instead of creating it again.
                      </FieldDescription>
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="employer-account-email">
                        Account email
                      </FieldLabel>
                      <Input
                        id="employer-account-email"
                        type="email"
                        value={data.session.email}
                        readOnly
                        className="bg-muted/40"
                      />
                    </Field>
                  </>
                ) : (
                  <>
                    <dl className="panel divide-y">
                      {[
                        ["Legal name", legalName.trim()],
                        ["Display name", displayName.trim()],
                        ["Domain", domain],
                        ["Account email", data.session.email],
                      ].map(([label, value]) => (
                        <div key={label} className="p-5">
                          <dt className="text-xs text-muted-foreground">
                            {label}
                          </dt>
                          <dd className="mt-2 break-words text-sm">{value}</dd>
                        </div>
                      ))}
                    </dl>
                    <div className="flex gap-3 rounded-lg bg-secondary p-5 text-sm">
                      <Building2 className="size-5 shrink-0" />
                      <p>
                        Submission creates a pending organization and pending
                        membership. It does not verify your organization, grant
                        approved hiring authority, or publish a vacancy.
                      </p>
                    </div>
                    <label className="flex items-start gap-3 text-sm leading-relaxed">
                      <input
                        type="checkbox"
                        checked={confirmed}
                        onChange={(event) => setConfirmed(event.target.checked)}
                        className="mt-1 size-4 shrink-0 accent-primary"
                      />
                      <span>
                        I have reviewed these details and request independent
                        verification for this organization. I understand that
                        hiring and signatory permissions require approval.
                      </span>
                    </label>
                  </>
                )}
              </fieldset>
              <div className="mt-9 flex justify-between gap-4 border-t pt-6">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={!step || busy}
                  onClick={() => {
                    setStep(0);
                    setAttempted(false);
                  }}
                >
                  <ArrowLeft className="size-4" />
                  Back
                </Button>
                <Button type="submit" size="lg" disabled={busy}>
                  {busy ? (
                    <>
                      <LoaderCircle className="size-4 animate-spin" />
                      Submitting…
                    </>
                  ) : step ? (
                    <>
                      Submit organization
                      <Check className="size-4" />
                    </>
                  ) : (
                    <>
                      Review details
                      <ArrowRight className="size-4" />
                    </>
                  )}
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </main>
  );
}
