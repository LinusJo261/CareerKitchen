"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Building2,
  FlaskConical,
  LoaderCircle,
  Play,
  UserRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { sendWorkspaceCommand, useWorkspace } from "@/lib/workspace";
import type { Role } from "@/lib/contracts";

async function responsePayload(response: Response) {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(
      typeof payload?.error === "string"
        ? payload.error
        : payload?.error?.message ||
            "Demo mode could not be opened. Please try again.",
    );
  }
  return payload;
}

async function enterDemo(role: Role) {
  await responsePayload(
    await fetch("/api/auth/session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        mode: "sample",
        account: role === "employer" ? "employer" : "candidate-000001",
      }),
      cache: "no-store",
    }),
  );
  // A full navigation clears the previous account's client-side workspace cache.
  window.location.assign(role === "employer" ? "/employer" : "/candidate");
}

export function DemoModeButton() {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<Role | null>(null);
  const [error, setError] = useState("");
  const pending = useRef(false);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setAvailable(null);
    setError("");
    fetch("/api/auth/config", { cache: "no-store", signal: controller.signal })
      .then(responsePayload)
      .then((configuration) => setAvailable(configuration?.sampleDemo === true))
      .catch((cause) => {
        if (!controller.signal.aborted) {
          setError(
            cause instanceof Error
              ? cause.message
              : "Unable to check demo availability.",
          );
        }
      });
    return () => controller.abort();
  }, [open]);

  async function start(role: Role) {
    if (pending.current || available !== true) return;
    pending.current = true;
    setBusy(role);
    setError("");
    try {
      await enterDemo(role);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to connect to the demo. Please try again.",
      );
      setBusy(null);
      pending.current = false;
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(value: boolean) => !pending.current && setOpen(value)}
    >
      <DialogTrigger asChild>
        <Button variant="outline">
          <Play aria-hidden="true" />
          Demo mode
        </Button>
      </DialogTrigger>
      <DialogContent showCloseButton={!busy} aria-busy={!!busy}>
        <DialogHeader>
          <p className="eyebrow mb-2 flex items-center gap-2">
            <FlaskConical aria-hidden="true" className="size-4" />A sample
            service
          </p>
          <DialogTitle className="font-serif text-3xl font-normal leading-tight">
            The same kitchen. A full house.
          </DialogTitle>
          <DialogDescription className="leading-relaxed">
            Explore 20,000 sample applicants and 20,000 sample jobs in the usual
            workspace. Run the matching algorithm, review its suggestions, and
            try both sides of an introduction.
          </DialogDescription>
        </DialogHeader>
        <p className="rounded-md border bg-secondary px-4 py-3 text-sm text-secondary-foreground">
          All profiles and activity in this mode are synthetic demo data. Your
          choices stay in the demo workspace.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Button
            size="lg"
            disabled={!!busy || available !== true}
            onClick={() => start("candidate")}
          >
            {busy === "candidate" ? (
              <LoaderCircle aria-hidden="true" className="animate-spin" />
            ) : (
              <UserRound aria-hidden="true" />
            )}
            {busy === "candidate" ? "Opening…" : "Try as a candidate"}
          </Button>
          <Button
            size="lg"
            variant="outline"
            disabled={!!busy || available !== true}
            onClick={() => start("employer")}
          >
            {busy === "employer" ? (
              <LoaderCircle aria-hidden="true" className="animate-spin" />
            ) : (
              <Building2 aria-hidden="true" />
            )}
            {busy === "employer" ? "Opening…" : "Try as an employer"}
          </Button>
        </div>
        {available === null && !error && (
          <p role="status" className="text-sm text-muted-foreground">
            Checking demo availability…
          </p>
        )}
        {available === false && (
          <p role="status" className="text-sm text-muted-foreground">
            Demo mode is not enabled on this server.
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function DemoModeBar({ role }: { role: Role }) {
  const { data, refresh } = useWorkspace();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const logoutKey = useRef<string | null>(null);
  const sample = data.context.sampleDemo;

  if (data.context.mode !== "sample") return null;

  async function act(action: "candidate" | "employer" | "match" | "exit") {
    if (pending.current) return;
    pending.current = true;
    setBusy(action);
    setError("");
    setNotice("");
    try {
      if (action === "candidate" || action === "employer") {
        await enterDemo(action);
        return;
      }
      if (action === "exit") {
        logoutKey.current ||= crypto.randomUUID();
        await responsePayload(
          await fetch("/api/auth/logout", {
            method: "POST",
            headers: { "Idempotency-Key": logoutKey.current },
            cache: "no-store",
          }),
        );
        window.location.assign("/");
        return;
      }
      const result = await sendWorkspaceCommand<{
        vacancies_considered: number;
        issued_count: number;
      }>("demo.reconcile", {});
      await refresh();
      setNotice(
        `Matching checked ${result.vacancies_considered} sample jobs and issued ${result.issued_count} new decision ${result.issued_count === 1 ? 'card' : 'cards'}. Attention limits and previous decisions still apply; introductions need a yes from both sides.`,
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The demo request could not be completed. Please try again.",
      );
    }
    setBusy(null);
    pending.current = false;
  }

  return (
    <section
      aria-label="Demo mode controls"
      className="border-b border-primary/20 bg-secondary text-secondary-foreground"
    >
      <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-4 px-5 py-4 md:px-8">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium">
            <FlaskConical
              aria-hidden="true"
              className="size-4 shrink-0 text-primary"
            />
            <span>Demo mode</span>
            {sample && (
              <span className="font-normal text-muted-foreground">
                · {sample.candidates.toLocaleString("en-US")} sample applicants
                · {sample.vacancies.toLocaleString("en-US")} sample jobs
              </span>
            )}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Synthetic profiles. Real matching algorithm. Choices stay in the
            demo workspace.
          </p>
          <nav
            aria-label="Demo browsing"
            className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-xs text-primary"
          >
            <Link
              href={`/${role}#sample-market`}
              className="underline-offset-4 hover:underline"
            >
              Browse market
            </Link>
            <Link
              href={
                role === "employer"
                  ? "/employer/candidates"
                  : "/candidate/opportunities"
              }
              className="underline-offset-4 hover:underline"
            >
              View suggestions
            </Link>
          </nav>
        </div>
        <div className="flex flex-wrap items-center gap-2" aria-busy={!!busy}>
          <div
            role="group"
            aria-label="Demo workspace"
            className="flex gap-1 rounded-md border p-1"
          >
            {(["candidate", "employer"] as const).map((side) => (
              <Button
                key={side}
                size="sm"
                variant={role === side ? "default" : "ghost"}
                aria-pressed={role === side}
                disabled={!!busy || role === side}
                onClick={() => act(side)}
              >
                {busy === side && (
                  <LoaderCircle aria-hidden="true" className="animate-spin" />
                )}
                {side === "candidate" ? "Candidate" : "Employer"}
              </Button>
            ))}
          </div>
          <Button
            size="sm"
            disabled={!!busy || sample?.ready === false}
            onClick={() => act("match")}
          >
            {busy === "match" ? (
              <LoaderCircle aria-hidden="true" className="animate-spin" />
            ) : (
              <Play aria-hidden="true" />
            )}
            {busy === "match" ? "Running matching…" : "Run matching"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!!busy}
            onClick={() => act("exit")}
          >
            {busy === "exit" ? "Exiting…" : "Exit demo"}
          </Button>
        </div>
      </div>
      {(error || notice || busy === "match") && (
        <p
          role={error ? "alert" : "status"}
          className={`mx-auto max-w-[1500px] px-5 pb-4 text-sm md:px-8 ${error ? "text-destructive" : "text-muted-foreground"}`}
        >
          {error ||
            notice ||
            "Running the matching algorithm with the demo profiles and attention limits…"}
        </p>
      )}
    </section>
  );
}
