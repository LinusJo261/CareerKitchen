"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSWRConfig } from "swr";
import { ArrowRight, Building2, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { AdaptiveOnboarding } from "@/components/navigation/adaptive-onboarding";
import { Brand } from "@/components/brand";
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

export function CandidateOnboarding() {
  return <EntryFrame><AdaptiveOnboarding /></EntryFrame>;
}
