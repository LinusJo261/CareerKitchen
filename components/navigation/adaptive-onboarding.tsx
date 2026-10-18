"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useWorkspace, WorkspaceError, type ApiSchema } from "@/lib/workspace";
import { navigationError } from "@/lib/navigation-chat";
import {
  onboardingDraft,
  onboardingConfirmation,
  onboardingAssistantTurn,
  onboardingIntroduction,
  onboardingSkipField,
  parseOnboardingReply,
  pendingOnboarding,
  reviewErrors,
  validOnboardingDraft,
  type OnboardingDraft,
  type OnboardingReply,
  type OnboardingTurn,
  type PendingOnboarding,
} from "@/lib/onboarding-chat";

const employment = [
  "FULL_TIME",
  "PART_TIME",
  "CONTRACT",
  "INTERNSHIP",
  "TEMPORARY",
];
const arrangements = ["REMOTE", "HYBRID", "ONSITE"];
const list = (value: string) =>
  value ? value.split(",").map((x) => x.trim()) : [];
const inputClass =
  "min-h-10 w-full rounded-md border bg-background px-3 py-2 text-sm";
const labelClass = "flex flex-col gap-2 text-sm font-medium";

function DraftEditor({
  draft,
  onChange,
  cap,
  onCapChange,
  disabled = false,
}: {
  draft: OnboardingDraft;
  onChange: (value: OnboardingDraft) => void;
  cap: number;
  onCapChange: (value: number) => void;
  disabled?: boolean;
}) {
  function update<K extends keyof OnboardingDraft>(
    key: K,
    value: OnboardingDraft[K],
  ) {
    onChange({ ...draft, [key]: value });
  }
  function toggle(
    key: "employment_types" | "work_modes",
    value: string,
    checked: boolean,
  ) {
    update(
      key,
      checked ? [...draft[key], value] : draft[key].filter((x) => x !== value),
    );
  }
  return (
    <fieldset disabled={disabled} className="grid gap-5 disabled:opacity-60">
      <legend className="mb-4 text-lg">Editable profile and keywords</legend>
      <label className={labelClass}>
        Headline
        <Input
          value={draft.headline ?? ""}
          maxLength={180}
          onChange={(e) => update("headline", e.target.value || null)}
        />
      </label>
      <label className={labelClass}>
        Region
        <Input
          value={draft.region ?? ""}
          maxLength={160}
          onChange={(e) => update("region", e.target.value || null)}
        />
      </label>
      <label className={labelClass}>
        Role families / keywords (comma separated)
        <Input
          value={draft.role_families.join(", ")}
          onChange={(e) => update("role_families", list(e.target.value))}
        />
      </label>
      <fieldset className="flex flex-wrap gap-4">
        <legend className="mb-2 text-sm font-medium">Employment types</legend>
        {employment.map((value) => (
          <label className="flex items-center gap-2 text-sm" key={value}>
            <input
              type="checkbox"
              checked={draft.employment_types.includes(value)}
              onChange={(e) =>
                toggle("employment_types", value, e.target.checked)
              }
            />
            {value.toLowerCase().replaceAll("_", " ")}
          </label>
        ))}
      </fieldset>
      <fieldset className="flex flex-wrap gap-4">
        <legend className="mb-2 text-sm font-medium">Work arrangements</legend>
        {arrangements.map((value) => (
          <label className="flex items-center gap-2 text-sm" key={value}>
            <input
              type="checkbox"
              checked={draft.work_modes.includes(value)}
              onChange={(e) => toggle("work_modes", value, e.target.checked)}
            />
            {value.toLowerCase()}
          </label>
        ))}
      </fieldset>
      <label className={labelClass}>
        Preferred locations (comma separated)
        <Input
          value={draft.locations.join(", ")}
          onChange={(e) => update("locations", list(e.target.value))}
        />
      </label>
      <label className={labelClass}>
        Summary
        <textarea
          className={inputClass}
          rows={3}
          maxLength={10000}
          value={draft.summary}
          onChange={(e) => update("summary", e.target.value)}
        />
      </label>
      <div className="grid gap-4 sm:grid-cols-3">
        <label className={labelClass}>
          Private pay minimum
          <Input
            type="number"
            min="0"
            step="0.01"
            value={draft.compensation_floor ?? ""}
            onChange={(e) =>
              update("compensation_floor", e.target.value || null)
            }
          />
        </label>
        <label className={labelClass}>
          Currency
          <Input
            maxLength={3}
            placeholder="USD"
            value={draft.currency ?? ""}
            onChange={(e) =>
              update("currency", e.target.value.toUpperCase() || null)
            }
          />
        </label>
        <label className={labelClass}>
          Pay period
          <select
            className={inputClass}
            value={draft.compensation_period ?? ""}
            onChange={(e) =>
              update(
                "compensation_period",
                (e.target.value ||
                  null) as OnboardingDraft["compensation_period"],
              )
            }
          >
            <option value="">Choose a period</option>
            {["ANNUAL", "MONTHLY", "HOURLY"].map((value) => (
              <option key={value} value={value}>
                {value.toLowerCase()}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-xs text-muted-foreground">
        Pay minimum and availability are excluded from Google requests unless
        you separately choose to share them. Anything you type in your answers
        is sent with your consent.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        {(["available_from", "available_until"] as const).map((key) => (
          <label className={labelClass} key={key}>
            {key === "available_from" ? "Available from" : "Available until"}{" "}
            (optional)
            <Input
              type="date"
              value={draft[key]?.slice(0, 10) ?? ""}
              onChange={(e) =>
                update(
                  key,
                  e.target.value ? `${e.target.value}T00:00:00Z` : null,
                )
              }
            />
          </label>
        ))}
      </div>
      <label className={labelClass}>
        Maximum opportunities awaiting your decision (1–10)
        <Input
          type="number"
          min={1}
          max={10}
          step={1}
          value={cap}
          onChange={(e) => onCapChange(Number(e.target.value))}
        />
      </label>
      <section className="grid gap-4" aria-labelledby="onboarding-skills">
        <h3 id="onboarding-skills" className="font-medium">
          Self-reported skills
        </h3>
        <p className="text-sm text-muted-foreground">
          Practice answers suggest levels; they do not verify a skill or predict
          hiring success. Edit every suggestion. Existing saved skills outside
          this draft are retained.
        </p>
        {draft.skills.map((skill, index) => (
          <fieldset className="grid gap-3 rounded-md border p-4" key={index}>
            <legend className="px-1 text-sm">Skill {index + 1}</legend>
            <label className={labelClass}>
              Skill keyword
              <Input
                maxLength={100}
                value={skill.name}
                onChange={(e) =>
                  update(
                    "skills",
                    draft.skills.map((s, i) =>
                      i === index ? { ...s, name: e.target.value } : s,
                    ),
                  )
                }
              />
            </label>
            <label className={labelClass}>
              Self-reported level
              <select
                className={inputClass}
                value={skill.level ?? ""}
                onChange={(e) =>
                  update(
                    "skills",
                    draft.skills.map((s, i) =>
                      i === index
                        ? {
                            ...s,
                            level: e.target.value
                              ? Number(e.target.value)
                              : null,
                          }
                        : s,
                    ),
                  )
                }
              >
                <option value="">Review and choose a level</option>
                {[1, 2, 3, 4, 5].map((level) => (
                  <option key={level} value={level}>
                    {level} —{" "}
                    {
                      [
                        "Learning",
                        "Basic tasks",
                        "Independent work",
                        "Complex work",
                        "Lead / mentor",
                      ][level - 1]
                    }
                  </option>
                ))}
              </select>
            </label>
            <label className={labelClass}>
              Practice evidence / your example
              <textarea
                className={inputClass}
                rows={2}
                maxLength={2000}
                value={skill.evidence}
                onChange={(e) =>
                  update(
                    "skills",
                    draft.skills.map((s, i) =>
                      i === index ? { ...s, evidence: e.target.value } : s,
                    ),
                  )
                }
              />
            </label>
            {skill.assessment_note ? (
              <p className="text-sm text-muted-foreground">
                Suggestion: {skill.assessment_note}
              </p>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              onClick={() =>
                update(
                  "skills",
                  draft.skills.filter((_, i) => i !== index),
                )
              }
            >
              Remove suggestion
            </Button>
          </fieldset>
        ))}
        <Button
          type="button"
          variant="outline"
          disabled={draft.skills.length >= 8}
          onClick={() =>
            update("skills", [
              ...draft.skills,
              { name: "", level: null, evidence: "", assessment_note: "" },
            ])
          }
        >
          Add a skill to review
        </Button>
      </section>
    </fieldset>
  );
}

export function AdaptiveOnboarding() {
  const workspace = useWorkspace();
  if (workspace.isLoading)
    return <p role="status">Loading your saved profile…</p>;
  if (workspace.error)
    return (
      <Alert variant="destructive">
        <AlertDescription role="alert">
          {workspace.error.message}{" "}
          <Link href="/sign-in" className="underline">
            Sign in again
          </Link>
        </AlertDescription>
      </Alert>
    );
  return (
    <OnboardingFlow
      key={workspace.data.session?.id ?? "candidate"}
      candidate={workspace.data.backend.candidate}
      skills={workspace.data.backend.skills}
      execute={workspace.execute}
    />
  );
}

function OnboardingFlow({
  candidate,
  skills,
  execute,
}: {
  candidate: ApiSchema["CandidateOut"] | null;
  skills: ApiSchema["SkillOut"][];
  execute: ReturnType<typeof useWorkspace>["execute"];
}) {
  const router = useRouter();
  // Keep the reviewed resource/version snapshot; background revalidation must not
  // silently rebind an unsaved form to a newer candidate version.
  const [baseline] = useState(candidate);
  const [draft, setDraft] = useState(() => onboardingDraft(candidate, skills));
  const [cap, setCap] = useState(candidate?.cap ?? 3);
  const [consent, setConsent] = useState(false);
  const [sharePrivate, setSharePrivate] = useState(false);
  const [started, setStarted] = useState(false);
  const [review, setReview] = useState(false);
  const [answer, setAnswer] = useState("");
  const [history, setHistory] = useState<OnboardingTurn[]>([]);
  const [result, setResult] = useState<OnboardingReply | null>(null);
  const [pending, setPending] = useState<PendingOnboarding | null>(null);
  const [savingPayload, setSavingPayload] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [terms, setTerms] = useState(false);
  const [privacy, setPrivacy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const questionHeading = useRef<HTMLHeadingElement>(null);
  useEffect(
    () => () => {
      generation.current += 1;
      controller.current?.abort();
    },
    [],
  );
  useEffect(() => {
    if (result) questionHeading.current?.focus();
  }, [result]);
  const errors = reviewErrors(draft, cap);
  const introduction = result ? onboardingIntroduction(result) : "";
  const locked = busy || pending !== null || savingPayload !== null;

  function clear() {
    generation.current += 1;
    controller.current?.abort();
    setDraft(onboardingDraft(null));
    setCap(3);
    setHistory([]);
    setResult(null);
    setPending(null);
    setSavingPayload(null);
    setAnswer("");
    setError("");
    setStarted(false);
    setReview(false);
    setConsent(false);
    setSharePrivate(false);
    setTerms(false);
    setPrivacy(false);
    setConfirmed(false);
    setBusy(false);
    inFlight.current = false;
  }
  async function requestTurn(request: PendingOnboarding) {
    if (inFlight.current || !consent) return;
    inFlight.current = true;
    const current = generation.current;
    setBusy(true);
    setError("");
    setPending(request);
    controller.current = new AbortController();
    try {
      const response = await fetch("/api/navigation/onboarding", {
        method: "POST",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": request.key,
        },
        body: request.body,
        signal: controller.current.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok)
        throw new Error(navigationError(payload, response.status));
      const next = parseOnboardingReply(payload);
      if (!next)
        throw new Error(
          "Career Chef returned an incomplete draft. Retry the saved request.",
        );
      if (current !== generation.current) return;
      setDraft((previous) => ({
        ...next.draft,
        ...(!sharePrivate
          ? {
              compensation_floor:
                next.draft.compensation_floor ?? previous.compensation_floor,
              available_from:
                next.draft.available_from ?? previous.available_from,
              available_until:
                next.draft.available_until ?? previous.available_until,
            }
          : {}),
      }));
      setHistory((turns) => [
        ...turns,
        { role: "user", content: request.message },
        onboardingAssistantTurn(next),
      ]);
      setResult(next);
      setPending(null);
      setAnswer("");
      setStarted(true);
    } catch (cause) {
      if (current === generation.current)
        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to contact Career Chef.",
        );
    } finally {
      if (current === generation.current) {
        setBusy(false);
        inFlight.current = false;
      }
    }
  }
  function send(message: string, nextDraft = draft) {
    if (locked || !consent) return;
    try {
      void requestTurn(
        pendingOnboarding(
          message,
          nextDraft,
          history,
          crypto.randomUUID(),
          sharePrivate,
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Check your answer.");
    }
  }
  async function save() {
    if (inFlight.current || !terms || !privacy || !confirmed || errors.length)
      return;
    const payload =
      savingPayload ?? onboardingConfirmation(draft, baseline, cap);
    inFlight.current = true;
    setSavingPayload(payload);
    setBusy(true);
    setError("");
    let failure =
      "Saving was not confirmed. Retry the same reviewed values, or return to editing.";
    const saved = await execute(
      "candidate.onboarding.confirm",
      payload,
      "Your reviewed profile and self-reported skills are saved.",
      (cause) => {
        failure = cause.message;
        if (
          cause instanceof WorkspaceError &&
          cause.status >= 400 &&
          cause.status < 500
        ) {
          setSavingPayload(null);
          setConfirmed(false);
          if (cause.status === 412)
            failure +=
              " Reload this page and review the current profile before confirming again. Your unsaved review has not been applied.";
        }
      },
    );
    setBusy(false);
    inFlight.current = false;
    if (saved) {
      clear();
      router.push("/candidate/profile");
      router.refresh();
    } else setError(failure);
  }
  return (
    <section
      className="rise flex w-full max-w-3xl flex-col gap-6"
      aria-busy={busy}
    >
      <div>
        <p className="eyebrow mb-3">Career Chef · your introduction</p>
        <h1 className="text-3xl font-normal">
          Build your profile through a conversation.
        </h1>
        <p className="mt-3 text-muted-foreground">
          Career Chef adapts one question at a time and offers practice prompts
          for your named skills. Nothing saves until you review and confirm.
        </p>
      </div>
      {error ? (
        <Alert variant="destructive">
          <AlertDescription role="alert">{error}</AlertDescription>
        </Alert>
      ) : null}
      {!review ? (
        <>
          <details className="rounded-md border p-4">
            <summary className="cursor-pointer font-medium">
              Inspect or edit the draft before sharing it
            </summary>
            <div className="mt-5">
              <DraftEditor
                draft={draft}
                onChange={setDraft}
                cap={cap}
                onCapChange={setCap}
                disabled={locked}
              />
            </div>
          </details>
          <fieldset
            disabled={locked}
            className="grid gap-3 rounded-md border p-4"
          >
            <legend className="px-1 text-sm font-medium">
              Your choice about Google Gemini
            </legend>
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => {
                  if (!e.target.checked) clear();
                  else setConsent(true);
                }}
              />
              <span>
                I agree to send my answers, completed conversation, and the
                editable draft shown above (profile keywords, preferences and
                skill examples) to Google Gemini to prepare suggestions. Do not
                include sensitive documents or account details. The website
                keeps this conversation in memory on this page. Google processes
                the information sent to it. The profile is saved only after my
                separate confirmation.
              </span>
            </label>
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={sharePrivate}
                onChange={(e) => setSharePrivate(e.target.checked)}
              />
              <span>
                Also share my draft compensation minimum and availability with
                Google. Otherwise these fields stay out of the draft sent to
                Google; anything I type in an answer is still shared.
              </span>
            </label>
          </fieldset>
          {!started && !pending ? (
            <div className="flex flex-wrap gap-3">
              <Button
                disabled={!consent || busy || !validStart(draft)}
                onClick={() =>
                  send(
                    "Help me build my career profile. Ask the most useful next question based on my draft.",
                  )
                }
              >
                Start with Career Chef
              </Button>
              <Button variant="outline" onClick={() => setReview(true)}>
                Review manually
              </Button>
            </div>
          ) : null}
          {result ? (
            <section
              className="grid gap-4 rounded-md bg-muted/40 p-5"
              aria-live="polite"
            >
              {introduction ? (
                <p className="whitespace-pre-wrap">{introduction}</p>
              ) : null}
              <h2
                ref={questionHeading}
                tabIndex={-1}
                className="whitespace-pre-wrap text-lg font-medium"
              >
                {result.question.prompt}
              </h2>
              {result.question.kind === "skill_probe" ? (
                <p className="text-sm text-muted-foreground">
                  Practice only. Suggested levels remain self-reported and
                  editable.
                </p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {result.question.choices.map((choice) => (
                  <Button
                    type="button"
                    key={choice}
                    variant="outline"
                    disabled={locked || !consent}
                    onClick={() => setAnswer(choice)}
                  >
                    {choice}
                  </Button>
                ))}
              </div>
            </section>
          ) : null}
          {started && !pending ? (
            <form
              className="grid gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                send(answer);
              }}
            >
              <label className={labelClass}>
                Your answer or correction
                <textarea
                  autoComplete="off"
                  className={inputClass}
                  rows={4}
                  maxLength={2000}
                  value={answer}
                  disabled={busy}
                  onChange={(e) => setAnswer(e.target.value)}
                />
              </label>
              <div className="flex flex-wrap gap-3">
                <Button
                  type="submit"
                  disabled={!consent || busy || !answer.trim()}
                >
                  Send answer
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busy || !consent}
                  onClick={() => {
                    const field = result
                      ? onboardingSkipField(result.question)
                      : "review";
                    send(
                      `Skip this question (${field}) and ask a different useful question.`,
                      {
                        ...draft,
                        skipped_fields: Array.from(
                          new Set([...draft.skipped_fields, field]),
                        ),
                      },
                    );
                  }}
                >
                  Skip this question
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setReview(true)}
                >
                  Finish and review
                </Button>
              </div>
            </form>
          ) : null}
          {pending ? (
            <div className="grid gap-3 rounded-md border p-4">
              <p className="text-sm">
                {busy
                  ? "Career Chef is preparing the next question…"
                  : "This request is saved in memory for an exact retry. Editing is paused."}
              </p>
              <div className="flex gap-3">
                <Button
                  disabled={busy || !consent}
                  onClick={() => void requestTurn(pending)}
                >
                  Retry saved request
                </Button>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    setPending(null);
                    setError("");
                  }}
                >
                  Discard failed request
                </Button>
              </div>
            </div>
          ) : null}
          {history.length ? (
            <details>
              <summary className="cursor-pointer text-sm">
                Completed conversation ({history.length / 2} turns)
              </summary>
              <ol className="mt-3 space-y-3">
                {history.map((turn, index) => (
                  <li
                    className="whitespace-pre-wrap rounded-md border p-3 text-sm"
                    key={index}
                  >
                    <strong>
                      {turn.role === "user" ? "You" : "Career Chef"}:
                    </strong>{" "}
                    {turn.content}
                  </li>
                ))}
              </ol>
            </details>
          ) : null}
        </>
      ) : (
        <>
          <div>
            <h2 className="text-2xl">Review before saving</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              You can correct every keyword and level. Practice evidence stays
              in the conversation; confirmation saves the reviewed profile and
              skill names/levels. Other saved experience, education and skills
              are preserved.
            </p>
          </div>
          <DraftEditor
            draft={draft}
            onChange={(value) => {
              setDraft(value);
              setConfirmed(false);
            }}
            cap={cap}
            onCapChange={(value) => {
              setCap(value);
              setConfirmed(false);
            }}
            disabled={locked}
          />
          {errors.length ? (
            <ul
              className="list-disc pl-5 text-sm text-destructive"
              aria-label="Review needed"
            >
              {errors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          ) : null}
          <fieldset disabled={locked} className="grid gap-4">
            <legend className="mb-3 font-medium">Confirm your choices</legend>
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={terms}
                onChange={(e) => setTerms(e.target.checked)}
              />
              <span>
                I accept the terms for introductions: interest is double opt-in
                and I control my attention capacity.
              </span>
            </label>
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={privacy}
                onChange={(e) => setPrivacy(e.target.checked)}
              />
              <span>
                I consent to storing and processing my profile for
                introductions. My compensation minimum stays private from
                employers; evidence sharing needs separate consent.
              </span>
            </label>
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>
                I reviewed the profile, preferences and self-reported skill
                names/levels and confirm they are accurate.
              </span>
            </label>
          </fieldset>
          <div className="flex flex-wrap gap-3">
            <Button
              disabled={
                busy || !!errors.length || !terms || !privacy || !confirmed
              }
              onClick={() => void save()}
            >
              {busy
                ? "Saving…"
                : savingPayload
                  ? "Retry the reviewed save"
                  : "Confirm and save profile"}
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                setSavingPayload(null);
                setReview(false);
                setConfirmed(false);
                setError("");
              }}
            >
              Return to conversation / edit
            </Button>
          </div>
        </>
      )}
      <div className="flex flex-wrap justify-between gap-3 border-t pt-4">
        <Button
          variant="ghost"
          disabled={savingPayload !== null || (busy && !pending)}
          onClick={clear}
        >
          Clear conversation and draft
        </Button>
        <Link href="/career-chef" className="self-center text-sm underline">
          Career Chef navigation
        </Link>
      </div>
    </section>
  );
}

function validStart(draft: OnboardingDraft) {
  // A blank draft is allowed. Incomplete editable skill rows must be completed
  // or removed before their content is sent to the schema-validated endpoint.
  return validOnboardingDraft(draft);
}
