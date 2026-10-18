"use client";

import { useId, useState } from "react";
import Link from "next/link";
import {
  BriefcaseBusiness,
  FileText,
  Plus,
  ShieldCheck,
  Sparkles,
  UserPlus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  EmptyNote,
  Initials,
  PageHeader,
  SectionTitle,
} from "@/components/workspace/kit";
import { useWorkspace } from "@/lib/workspace";
import type { components } from "@/packages/api-client/src/schema";

type Vacancy = components["schemas"]["VacancyOut"];
type Policy = components["schemas"]["PolicyOut"];
type Match = components["schemas"]["MatchOut"];
type Requirement = components["schemas"]["RequirementOut"];
type FormField = {
  name: string;
  label: string;
  type?: string;
  value?: string | number;
  options?: readonly (string | { value: string; label: string })[];
  required?: boolean;
  min?: number;
  max?: number;
  step?: string;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  description?: string;
};
type FormValues = Record<string, FormDataEntryValue>;

const human = (value: string) =>
  value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (x) => x.toUpperCase());
const date = (value: string) => new Date(value).toLocaleString();
const iso = (value: FormDataEntryValue | undefined) =>
  new Date(String(value)).toISOString();
const localDate = (value?: string | null) => {
  if (!value) return "";
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
};
const selectClass =
  "border-input bg-background min-h-9 w-full rounded-md border px-3 py-2 text-sm";

function Fields({ fields }: { fields: FormField[] }) {
  const prefix = useId();
  return (
    <>
      {fields.map((f) => (
        <Field key={f.name}>
          <FieldLabel htmlFor={`${prefix}-${f.name}`}>{f.label}</FieldLabel>
          {f.options ? (
            <select
              id={`${prefix}-${f.name}`}
              name={f.name}
              defaultValue={f.value ?? ""}
              required={f.required !== false}
              className={selectClass}
            >
              <option value="" disabled>
                Choose…
              </option>
              {f.options.map((o) => (
                <option
                  key={typeof o === "string" ? o : o.value}
                  value={typeof o === "string" ? o : o.value}
                >
                  {typeof o === "string" ? human(o) : o.label}
                </option>
              ))}
            </select>
          ) : f.type === "textarea" ? (
            <Textarea
              id={`${prefix}-${f.name}`}
              name={f.name}
              defaultValue={f.value}
              required={f.required !== false}
              minLength={f.minLength}
              maxLength={f.maxLength}
              rows={4}
            />
          ) : (
            <Input
              id={`${prefix}-${f.name}`}
              name={f.name}
              type={f.type ?? "text"}
              defaultValue={f.value}
              required={f.required !== false}
              min={f.min}
              max={f.max}
              step={f.step}
              minLength={f.minLength}
              maxLength={f.maxLength}
              pattern={f.pattern}
            />
          )}
          {f.description && (
            <FieldDescription>{f.description}</FieldDescription>
          )}
        </Field>
      ))}
    </>
  );
}

function ActionDialog({
  title,
  description,
  trigger,
  fields = [],
  submitLabel = "Save",
  affirmation,
  onSubmit,
}: {
  title: string;
  description: string;
  trigger: string;
  fields?: FormField[];
  submitLabel?: string;
  affirmation?: string;
  onSubmit: (values: FormValues) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const values = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true);
    try {
      if (await onSubmit(values)) setOpen(false);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          {trigger}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <form onSubmit={submit} className="flex flex-col gap-5">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <Fields fields={fields} />
          {affirmation && (
            <label className="flex gap-3 text-sm">
              <input type="checkbox" name="affirm" required />
              {affirmation}
            </label>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Saving…" : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function VacanciesPage() {
  const { data, execute } = useWorkspace();
  const [filter, setFilter] = useState("All");
  const list = data.backend.vacancies.filter(
    (v) => filter === "All" || v.state === filter,
  );
  return (
    <>
      <PageHeader
        eyebrow={data.organization.name}
        title="Job openings"
        description="Publish clear role terms, compensation and requirements. Changes use the version you reviewed."
        actions={<VacancyDialog />}
      />
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={filter}
        onValueChange={(v) => v && setFilter(v)}
        className="mb-5"
        aria-label="Filter job openings"
      >
        {["All", "ACTIVE", "DRAFT", "PAUSED", "CLOSED", "FILLED"].map((f) => (
          <ToggleGroupItem key={f} value={f}>
            {f === "All" ? f : human(f)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      {!list.length ? (
        <EmptyNote
          icon={BriefcaseBusiness}
          title="No job openings here"
          description="Create a draft job opening after your organization membership has been approved."
        />
      ) : (
        <ul className="grid gap-4 lg:grid-cols-2">
          {list.map((v) => (
            <li
              key={`${v.id}-${v.version}`}
              className="panel flex flex-col gap-4 p-6"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-lg font-medium">{v.title}</p>
                  <p className="text-sm text-muted-foreground">
                    {v.location_region || "Remote"} · {human(v.work_mode)} ·{" "}
                    {human(v.employment_type)}
                  </p>
                </div>
                <Badge variant={v.state === "ACTIVE" ? "secondary" : "outline"}>
                  {human(v.state)}
                </Badge>
              </div>
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                {v.description}
              </p>
              <div className="flex flex-wrap gap-2">
                {v.requirements.map((r) => (
                  <Badge key={r.id} variant="outline">
                    {r.description} · {human(r.kind)}
                  </Badge>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">
                {v.currency} {Number(v.pay_min).toLocaleString()} –{" "}
                {Number(v.pay_max).toLocaleString()} /{" "}
                {human(v.compensation_period)} · {v.openings_remaining}{" "}
                opening(s) · {v.cap} active decisions maximum
              </p>
              {!["CLOSED", "FILLED"].includes(v.state) && (
                <div className="mt-auto flex flex-wrap gap-2 border-t pt-4">
                  <VacancyDialog vacancy={v} />
                  <RequirementDialog vacancy={v} />
                  {v.state === "ACTIVE" ? (
                    <ActionDialog
                      trigger="Pause"
                      title="Pause job opening?"
                      description="Pending introductions will be cancelled until you publish again."
                      submitLabel="Pause job opening"
                      onSubmit={() =>
                        execute(
                          "vacancy.pause",
                          { id: v.id, expected_version: v.version },
                          "Job opening paused.",
                        )
                      }
                    />
                  ) : (
                    <ActionDialog
                      trigger="Publish"
                      title="Publish job opening?"
                      description="Confirm that you have reviewed this version and its requirements. Organization verification and attention ceilings are checked by the backend."
                      submitLabel="Publish"
                      affirmation="I have reviewed these role terms and requirements."
                      onSubmit={() =>
                        execute(
                          "vacancy.activate",
                          { id: v.id, expected_version: v.version },
                          "Job opening published.",
                        )
                      }
                    />
                  )}
                  <ActionDialog
                    trigger="Close job opening"
                    title="Close job opening?"
                    description="This closes pending introductions. A closed job opening cannot be reopened."
                    submitLabel="Close job opening"
                    onSubmit={() =>
                      execute(
                        "vacancy.close",
                        { id: v.id, expected_version: v.version },
                        "Job opening closed.",
                      )
                    }
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function VacancyDialog({ vacancy: v }: { vacancy?: Vacancy }) {
  const { data, execute } = useWorkspace();
  const org =
    data.backend.organizations.find(
      (o) => o.id === data.context.organizationId,
    ) ?? data.backend.organizations[0];
  const fields: FormField[] = [
    ...(!v
      ? [
          {
            name: "org_id",
            label: "Organization",
            value: org?.id,
            options: data.backend.organizations.map((o) => ({
              value: o.id,
              label: o.display_name,
            })),
          },
        ]
      : []),
    {
      name: "title",
      label: "Role title",
      value: v?.title,
      minLength: 3,
      maxLength: 180,
    },
    {
      name: "role_family",
      label: "Role family",
      value: v?.role_family,
      minLength: 2,
      maxLength: 120,
    },
    {
      name: "description",
      label: "Role description",
      value: v?.description,
      type: "textarea",
      minLength: 30,
      maxLength: 30000,
    },
    {
      name: "pay_min",
      label: "Minimum pay",
      value: v ? String(v.pay_min) : "",
      type: "number",
      min: 0,
      step: "0.01",
    },
    {
      name: "pay_max",
      label: "Maximum pay",
      value: v ? String(v.pay_max) : "",
      type: "number",
      min: 0,
      step: "0.01",
    },
    {
      name: "currency",
      label: "Currency",
      value: v?.currency ?? "USD",
      pattern: "[A-Z]{3}",
      maxLength: 3,
    },
    {
      name: "compensation_period",
      label: "Pay period",
      value: v?.compensation_period ?? "ANNUAL",
      options: ["ANNUAL", "MONTHLY", "HOURLY"],
    },
    {
      name: "employment_type",
      label: "Employment type",
      value: v?.employment_type ?? "FULL_TIME",
      options: [
        "FULL_TIME",
        "PART_TIME",
        "CONTRACT",
        "INTERNSHIP",
        "TEMPORARY",
      ],
    },
    {
      name: "work_mode",
      label: "Work arrangement",
      value: v?.work_mode ?? "HYBRID",
      options: ["REMOTE", "HYBRID", "ONSITE"],
    },
    {
      name: "location_region",
      label: "Location / region",
      value: v?.location_region,
      required: false,
      maxLength: 160,
      description: "Required for hybrid and on-site roles.",
    },
    {
      name: "openings_total",
      label: "Openings",
      value: v?.openings_total ?? 1,
      type: "number",
      min: 1,
      max: 100,
    },
    {
      name: "cap",
      label: "Active decision ceiling",
      value: v?.cap ?? 10,
      type: "number",
      min: 1,
      max: 10,
    },
    {
      name: "deadline_at",
      label: "Deadline (local time)",
      value: localDate(v?.deadline_at),
      type: "datetime-local",
      required: false,
    },
  ];
  if (!v && !org)
    return (
      <Button asChild>
        <Link href="/employer/organization">
          <Plus data-icon="inline-start" />
          Create organization first
        </Link>
      </Button>
    );
  return (
    <ActionDialog
      trigger={v ? "Edit terms" : "New job opening"}
      title={v ? "Edit job opening" : "Create a draft job opening"}
      description={
        v
          ? "Editing an active role pauses it and invalidates previous role terms."
          : "Saved as a draft. Publish after reviewing its requirements."
      }
      fields={fields}
      submitLabel={v ? "Save terms" : "Save draft"}
      onSubmit={(f) =>
        execute(
          v ? "vacancy.save" : "vacancy.create",
          {
            ...f,
            org_id: v?.org_id ?? f.org_id,
            pay_min: String(f.pay_min),
            pay_max: String(f.pay_max),
            openings_total: Number(f.openings_total),
            cap: Number(f.cap),
            deadline_at: f.deadline_at ? iso(f.deadline_at) : null,
            start_from: v?.start_from ?? null,
            start_until: v?.start_until ?? null,
            ...(v ? { id: v.id, expected_version: v.version } : {}),
          },
          v
            ? "Job opening saved. Review and publish the new version."
            : "Draft job opening created.",
        )
      }
    />
  );
}

function RequirementDialog({ vacancy: v }: { vacancy: Vacancy }) {
  const { execute } = useWorkspace();
  return (
    <ActionDialog
      trigger="Add requirement"
      title="Add a job requirement"
      description="Essential requirements need a documented job-related reason. Changing requirements invalidates earlier decisions."
      fields={[
        {
          name: "key",
          label: "Requirement key",
          minLength: 2,
          maxLength: 120,
          pattern: "[a-z0-9_.+\\-]+",
          description: "A stable key such as python or customer_support.",
        },
        {
          name: "description",
          label: "Description",
          type: "textarea",
          minLength: 5,
          maxLength: 2000,
        },
        {
          name: "kind",
          label: "Requirement type",
          value: "PREFERENCE",
          options: ["PREFERENCE", "ESSENTIAL", "AMBIGUOUS"],
        },
        {
          name: "lawful_reason",
          label: "Job-related reason (required for essential requirements)",
          type: "textarea",
          required: false,
          minLength: 10,
          maxLength: 2000,
        },
      ]}
      affirmation="I have reviewed this requirement for this role."
      submitLabel="Save requirement"
      onSubmit={(f) =>
        execute(
          "requirement.create",
          {
            vacancyId: v.id,
            expected_version: v.version,
            key: f.key,
            description: f.description,
            kind: f.kind,
            lawful_reason: f.lawful_reason || null,
            human_reviewed: true,
          },
          "Requirement saved. Review the new role version before publishing.",
        )
      }
    />
  );
}

const STAGES = [
  "MUTUAL_MATCH",
  "INTERVIEWING",
  "OFFERED",
  "OFFER_ACCEPTED",
  "START_CONFIRMED",
];
const STAGE_NAMES: Record<string, string> = {
  MUTUAL_MATCH: "Mutual interest",
  INTERVIEWING: "Interviewing",
  OFFERED: "Offer sent",
  OFFER_ACCEPTED: "Offer accepted",
  START_CONFIRMED: "Employment confirmed",
};

export function PipelinePage() {
  const { data } = useWorkspace();
  const [vacancyId, setVacancyId] = useState("All");
  const entries = data.backend.matches.filter(
    (m) => vacancyId === "All" || m.vacancy.id === vacancyId,
  );
  return (
    <>
      <PageHeader
        eyebrow="Hiring progress"
        title="Pipeline"
        description="Only mutual matches enter the pipeline. An offer, its acceptance and a verified employment start remain distinct steps."
        actions={
          <select
            className={selectClass}
            aria-label="Filter by job opening"
            value={vacancyId}
            onChange={(e) => setVacancyId(e.target.value)}
          >
            <option value="All">All job openings</option>
            {data.backend.vacancies.map((v) => (
              <option key={v.id} value={v.id}>
                {v.title}
              </option>
            ))}
          </select>
        }
      />
      <div className="-mx-1 flex gap-4 overflow-x-auto px-1 pb-4">
        {[...STAGES, "CLOSED"].map((stage) => {
          const col = entries.filter((p) =>
            stage === "CLOSED"
              ? p.state.startsWith("CLOSED")
              : p.state === stage,
          );
          return (
            <section
              key={stage}
              className="flex w-72 shrink-0 flex-col gap-3"
              aria-label={STAGE_NAMES[stage] ?? "Closed"}
            >
              <header className="flex justify-between px-1">
                <h2 className="text-sm font-medium">
                  {STAGE_NAMES[stage] ?? "Closed"}
                </h2>
                <span className="text-xs text-muted-foreground">
                  {col.length}
                </span>
              </header>
              <div className="flex min-h-40 flex-col gap-3 rounded-xl bg-muted/60 p-3">
                {!col.length && (
                  <p className="p-4 text-center text-xs text-muted-foreground">
                    No one here yet
                  </p>
                )}
                {col.map((m) => (
                  <article
                    key={`${m.id}-${m.cycle_version}`}
                    className="panel flex flex-col gap-3 p-4"
                  >
                    <div className="flex items-center gap-3">
                      <Initials
                        name={m.candidate.headline}
                        className="size-8 text-xs"
                      />
                      <div>
                        <p className="text-sm font-medium">
                          {m.candidate.headline}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {m.vacancy.title}
                        </p>
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {human(m.state)}
                    </p>
                    {m.state === "MUTUAL_MATCH" && <StageDialog match={m} />}
                    {["MUTUAL_MATCH", "INTERVIEWING", "OFFERED"].includes(
                      m.state,
                    ) && <StageDialog match={m} reject />}
                    {m.state === "INTERVIEWING" && (
                      <Button asChild size="sm" variant="outline">
                        <Link href="/employer/offers">Prepare offer</Link>
                      </Button>
                    )}
                    {m.state === "OFFER_ACCEPTED" && (
                      <p className="text-xs text-muted-foreground">
                        Employment requires an actual start and independent
                        verification.
                      </p>
                    )}
                  </article>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}

function StageDialog({
  match: m,
  reject = false,
}: {
  match: Match;
  reject?: boolean;
}) {
  const { execute } = useWorkspace();
  return (
    <ActionDialog
      trigger={reject ? "Close process" : "Begin interviewing"}
      title={reject ? "Close this hiring process?" : "Begin interviewing"}
      description={
        reject
          ? "The process will close for both participants."
          : "Record the real hiring decision that starts the interview process."
      }
      fields={[
        {
          name: "source_reference",
          label: "Decision reference or reason",
          type: "textarea",
          minLength: 5,
          maxLength: 1000,
        },
      ]}
      submitLabel="Confirm decision"
      onSubmit={(f) =>
        execute(
          "stage.update",
          {
            matchId: m.id,
            expected_version: m.cycle_version,
            stage: reject ? "CLOSED_REJECTED" : "INTERVIEWING",
            source_reference: f.source_reference,
          },
          "Hiring process updated.",
        )
      }
    />
  );
}

export function EmployerOffersPage() {
  const { data, execute } = useWorkspace();
  const ready = data.backend.matches.filter((m) => m.state === "INTERVIEWING");
  const sent = data.backend.matches.flatMap((m) =>
    m.offers.map((o) => ({
      ...o,
      role: m.vacancy.title,
      person: m.candidate.headline,
    })),
  );
  return (
    <>
      <PageHeader
        eyebrow="Formal offers"
        title="Offers"
        description="An authorized signatory issues a formal offer after interviewing. Candidates respond separately; acceptance does not confirm employment."
      />
      <div className="flex max-w-3xl flex-col gap-10">
        <section>
          <SectionTitle title="Ready for an offer" />
          {!ready.length ? (
            <EmptyNote
              icon={FileText}
              title="No one is interviewing yet"
              description="Start interviewing for a mutual match in your pipeline."
            />
          ) : (
            <ul className="panel divide-y">
              {ready.map((m) => (
                <li
                  key={`${m.id}-${m.cycle_version}`}
                  className="flex flex-wrap items-center gap-4 p-5"
                >
                  <Initials name={m.candidate.headline} />
                  <div className="flex-1">
                    <p className="font-medium">{m.candidate.headline}</p>
                    <p className="text-sm text-muted-foreground">
                      {m.vacancy.title}
                    </p>
                  </div>
                  <ActionDialog
                    trigger="Prepare offer"
                    title={`Formal offer for ${m.vacancy.title}`}
                    description="Requires recent authentication and independently approved signatory authority."
                    fields={[
                      {
                        name: "terms",
                        label: "Complete offer terms",
                        type: "textarea",
                        minLength: 30,
                        maxLength: 30000,
                        description:
                          "Include the actual compensation, work arrangement and conditions.",
                      },
                      {
                        name: "start_at",
                        label: "Proposed start (local time)",
                        type: "datetime-local",
                      },
                      {
                        name: "expires_at",
                        label: "Response deadline (local time)",
                        type: "datetime-local",
                        description: "Must be in the next 90 days.",
                      },
                    ]}
                    affirmation="I am authorized to issue this offer and have reviewed its complete terms."
                    submitLabel="Issue formal offer"
                    onSubmit={(f) =>
                      execute(
                        "offer.create",
                        {
                          matchId: m.id,
                          expected_version: m.cycle_version,
                          terms: f.terms,
                          start_at: iso(f.start_at),
                          expires_at: iso(f.expires_at),
                          affirm_human_authority: true,
                        },
                        "Formal offer issued. Awaiting the candidate’s response.",
                      )
                    }
                  />
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <SectionTitle title="Recorded offers" />
          {!sent.length ? (
            <p className="text-sm text-muted-foreground">
              No formal offers have been recorded.
            </p>
          ) : (
            <ul className="panel divide-y">
              {sent.map((o) => (
                <li key={o.id} className="flex flex-col gap-3 p-5">
                  <div className="flex justify-between gap-4">
                    <div>
                      <p className="font-medium">{o.role}</p>
                      <p className="text-sm text-muted-foreground">
                        {o.person}
                      </p>
                    </div>
                    <Badge variant="outline">{human(o.status)}</Badge>
                  </div>
                  <p className="whitespace-pre-wrap text-sm">{o.terms}</p>
                  <p className="text-xs text-muted-foreground">
                    Respond by {date(o.expires_at)} · Proposed start{" "}
                    {date(o.start_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

export function OrganizationPage() {
  const { data, execute } = useWorkspace();
  return (
    <>
      <PageHeader
        eyebrow="Your organization"
        title="Organization"
        description="Organization verification and privileged authority require independent review."
        actions={
          <ActionDialog
            trigger="Create organization"
            title="Create your organization"
            description="Creation starts verification. It does not grant approved hiring or signatory authority."
            fields={[
              {
                name: "legal_name",
                label: "Legal name",
                minLength: 3,
                maxLength: 200,
              },
              {
                name: "display_name",
                label: "Display name",
                minLength: 2,
                maxLength: 120,
              },
              {
                name: "domain",
                label: "Organization domain",
                pattern: "[a-z0-9.\\-]+\\.[a-z]{2,}",
                maxLength: 200,
                description:
                  "Enter the lowercase domain, for example company.com.",
              },
            ]}
            submitLabel="Submit organization"
            onSubmit={(f) =>
              execute(
                "organization.create",
                f,
                "Organization submitted for independent verification.",
              )
            }
          />
        }
      />
      {!data.backend.organizations.length ? (
        <EmptyNote
          icon={BriefcaseBusiness}
          title="Create your organization"
          description="Submit your organization details to begin independent verification."
        />
      ) : (
        <div className="grid max-w-5xl gap-6 lg:grid-cols-2">
          {data.backend.organizations.map((org) => (
            <article
              key={`${org.id}-${org.version}`}
              className="panel flex flex-col gap-5 p-6"
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-lg">{org.display_name}</h2>
                <Badge
                  variant={
                    org.verification_state === "VERIFIED"
                      ? "secondary"
                      : "outline"
                  }
                >
                  {human(org.verification_state)}
                </Badge>
              </div>
              <dl className="grid gap-3 text-sm">
                <div>
                  <dt className="text-xs text-muted-foreground">Legal name</dt>
                  <dd>{org.legal_name}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Domain</dt>
                  <dd>{org.domain}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">
                    Active job opening capacity
                  </dt>
                  <dd>{org.active_role_capacity}</dd>
                </div>
              </dl>
              <ActionDialog
                trigger="Edit display name"
                title="Organization display name"
                description="Update the public organization name."
                fields={[
                  {
                    name: "display_name",
                    label: "Display name",
                    value: org.display_name,
                    minLength: 2,
                    maxLength: 120,
                  },
                ]}
                onSubmit={(f) =>
                  execute(
                    "organization.save",
                    { id: org.id, expected_version: org.version, ...f },
                    "Organization updated.",
                  )
                }
              />
            </article>
          ))}
        </div>
      )}
    </>
  );
}

export function PactPage() {
  const { data, execute } = useWorkspace();
  const [lookup, setLookup] = useState("");
  const [vacancyId, setVacancyId] = useState("");
  const vacancy = data.backend.vacancies.find((v) => v.id === vacancyId);
  return (
    <>
      <PageHeader
        eyebrow="Agreement-first"
        title="PACT terms"
        description="Authorize exact role versions and terms. PACT confirmation remains separate from an offer and verified employment."
      />
      <div className="grid max-w-5xl gap-8 lg:grid-cols-2">
        <div className="flex flex-col gap-5">
          <section className="panel flex flex-col gap-4 p-6">
            <SectionTitle
              title="Create policy draft"
              description="Requires independently approved signatory authority and recent authentication."
            />
            <Field>
              <FieldLabel htmlFor="policy-vacancy">Job opening version</FieldLabel>
              <select
                id="policy-vacancy"
                className={selectClass}
                value={vacancyId}
                onChange={(e) => setVacancyId(e.target.value)}
              >
                <option value="">Choose a job opening</option>
                {data.backend.vacancies
                  .filter((v) => ["DRAFT", "ACTIVE"].includes(v.state))
                  .map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.title} · v{v.version}
                    </option>
                  ))}
              </select>
            </Field>
            {vacancy && (
              <div
                key={`${vacancy.id}-${vacancy.version}`}
                className="flex flex-col gap-4"
              >
                <p className="text-sm text-muted-foreground">
                  {vacancy.currency} {String(vacancy.pay_min)} –{" "}
                  {String(vacancy.pay_max)} · {human(vacancy.work_mode)} ·{" "}
                  {vacancy.requirements.length} requirements
                </p>
                <ActionDialog
                  trigger="Draft policy for this version"
                  title="Draft PACT policy"
                  description={`Applies to ${vacancy.title}, role version ${vacancy.version}. Review the exact terms before authorization.`}
                  fields={[
                    {
                      name: "policy_text",
                      label: "Policy terms",
                      type: "textarea",
                      minLength: 10,
                      maxLength: 10000,
                    },
                    {
                      name: "stage",
                      label: "Authorized stage",
                      value: "SCREENING",
                      options: ["SCREENING", "INTERVIEW", "CONDITIONAL_OFFER"],
                    },
                    {
                      name: "expires_at",
                      label: "Expiry (local time)",
                      type: "datetime-local",
                      description: "Within the next 30 days.",
                    },
                  ]}
                  submitLabel="Create draft"
                  onSubmit={(f) =>
                    execute(
                      "policy.create",
                      {
                        vacancyId: vacancy.id,
                        expected_version: vacancy.version,
                        terms_hash: vacancy.terms_hash,
                        ...f,
                        expires_at: iso(f.expires_at),
                      },
                      "PACT policy draft created.",
                    )
                  }
                />
              </div>
            )}
          </section>
          <form
            className="panel flex flex-col gap-3 p-5"
            onSubmit={async (e) => {
              e.preventDefault();
              await execute("policy.load", { id: lookup });
            }}
          >
            <Field>
              <FieldLabel htmlFor="policy-lookup">
                Open existing policy by ID
              </FieldLabel>
              <Input
                id="policy-lookup"
                required
                pattern="[0-9a-fA-F\\-]{36}"
                value={lookup}
                onChange={(e) => setLookup(e.target.value)}
              />
            </Field>
            <Button type="submit" variant="outline">
              Load policy
            </Button>
          </form>
          <Alert>
            <ShieldCheck />
            <AlertTitle>Independently checked authority</AlertTitle>
            <AlertDescription>
              Privileged roles require independent review. Changes to role terms
              invalidate earlier policy readiness.
            </AlertDescription>
          </Alert>
        </div>
        <div className="flex flex-col gap-5">
          {data.backend.policies.length ? (
            data.backend.policies.map((p) => (
              <PolicyCard key={`${p.id}-${p.version}`} policy={p} />
            ))
          ) : (
            <p className="text-sm text-muted-foreground">
              No policy drafts or authorizations are available.
            </p>
          )}
        </div>
      </div>
    </>
  );
}

function PolicyCard({ policy: p }: { policy: Policy }) {
  const { execute } = useWorkspace();
  return (
    <article className="panel flex flex-col gap-4 p-5">
      <div className="flex justify-between gap-3">
        <p className="text-sm font-medium">
          {human(p.stage)} · v{p.version}
        </p>
        <Badge variant="outline">{human(p.state)}</Badge>
      </div>
      <p className="break-all font-mono text-xs text-muted-foreground">
        {p.id}
      </p>
      <p className="whitespace-pre-wrap text-sm">{p.policy_text}</p>
      <p className="text-xs text-muted-foreground">
        Expires {date(p.expires_at)} · {Object.keys(p.scope).length} exact role
        version(s)
      </p>
      {p.state === "DRAFT" && (
        <ActionDialog
          trigger="Authorize terms"
          title="Authorize these exact terms?"
          description={p.policy_text}
          affirmation="I have reviewed this exact policy scope and hold the required human authority."
          submitLabel="Authorize"
          onSubmit={() =>
            execute(
              "policy.authorize",
              {
                id: p.id,
                expected_version: p.version,
                scope_hash: p.scope_hash,
                affirm_human_authority: true,
              },
              "PACT terms authorized.",
            )
          }
        />
      )}
      {p.state === "AUTHORIZED" && (
        <ActionDialog
          trigger="Revoke terms"
          title="Revoke policy?"
          description="Existing readiness dependent on this policy will be invalidated."
          fields={[
            {
              name: "reason",
              label: "Revocation reason",
              minLength: 1,
              maxLength: 500,
            },
          ]}
          submitLabel="Revoke"
          onSubmit={(f) =>
            execute(
              "policy.revoke",
              { id: p.id, expected_version: p.version, reason: f.reason },
              "PACT terms revoked.",
            )
          }
        />
      )}
    </article>
  );
}

export function WitnessPage() {
  const { data, execute } = useWorkspace();
  const ambiguous = data.backend.vacancies.flatMap((v) =>
    v.requirements
      .filter((r) => r.kind === "AMBIGUOUS")
      .map((r) => ({ vacancy: v, requirement: r })),
  );
  return (
    <>
      <PageHeader
        eyebrow="Hiring clarity"
        title="WITNESS"
        description="Review actual ambiguous role requirements. Changes need an authorized human decision; essential qualifications cannot be relaxed."
      />
      <div className="flex max-w-3xl flex-col gap-8">
        {!ambiguous.length ? (
          <EmptyNote
            icon={Sparkles}
            title="No ambiguous requirements recorded"
            description="This reflects the recorded requirements. It is not a certification of hiring reliability."
          />
        ) : (
          ambiguous.map(({ vacancy, requirement }) => (
            <article
              key={`${requirement.id}-${vacancy.version}`}
              className="panel flex flex-col gap-4 p-6"
            >
              <Badge variant="outline" className="self-start">
                Ambiguous requirement
              </Badge>
              <div>
                <h2 className="text-lg">{vacancy.title}</h2>
                <p className="mt-2 text-sm">{requirement.description}</p>
              </div>
              <ClarificationDialog
                vacancy={vacancy}
                requirement={requirement}
              />
            </article>
          ))
        )}
        {!!data.backend.clarifications.length && (
          <section>
            <SectionTitle title="Clarification requests" />
            <ul className="panel divide-y">
              {data.backend.clarifications.map((c) => (
                <li
                  key={`${c.id}-${c.version}`}
                  className="flex flex-col gap-4 p-5"
                >
                  <div className="flex justify-between gap-3">
                    <p className="text-sm">{c.proposed_text}</p>
                    <Badge variant="outline">{human(c.status)}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Expires {date(c.expires_at)}
                  </p>
                  {c.status === "REQUESTED" && (
                    <div className="flex gap-2">
                      {[false, true].map((approved) => (
                        <ActionDialog
                          key={String(approved)}
                          trigger={approved ? "Review approval" : "Deny"}
                          title={
                            approved
                              ? "Approve this clarification?"
                              : "Deny clarification?"
                          }
                          description={
                            approved
                              ? `This applies the proposed preference wording: ${c.proposed_text}`
                              : "The role requirement will remain as recorded."
                          }
                          affirmation="I hold the required signatory authority and have reviewed this request."
                          submitLabel={
                            approved ? "Approve change" : "Deny request"
                          }
                          onSubmit={() =>
                            execute(
                              "clarification.respond",
                              {
                                id: c.id,
                                expected_version: c.version,
                                vacancy_id: c.vacancy_id,
                                role_version: c.role_version,
                                requirement_id: c.requirement_id,
                                approved,
                                affirm_human_authority: true,
                              },
                              approved
                                ? "Clarification approved and applied."
                                : "Clarification denied.",
                            )
                          }
                        />
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </>
  );
}

function ClarificationDialog({
  vacancy: v,
  requirement: r,
}: {
  vacancy: Vacancy;
  requirement: Requirement;
}) {
  const { execute } = useWorkspace();
  return (
    <ActionDialog
      trigger="Propose clarification"
      title="Clarify requirement"
      description="Propose a job-related preference. An authorized signatory must review it before role terms change."
      fields={[
        {
          name: "proposed_text",
          label: "Proposed preference wording",
          type: "textarea",
          minLength: 10,
          maxLength: 2000,
        },
        {
          name: "reason",
          label: "Reason",
          type: "textarea",
          minLength: 10,
          maxLength: 1000,
        },
        {
          name: "expires_at",
          label: "Review deadline (local time)",
          type: "datetime-local",
          description: "Within the next seven days.",
        },
      ]}
      submitLabel="Request clarification"
      onSubmit={(f) =>
        execute(
          "clarification.create",
          {
            vacancyId: v.id,
            expected_version: v.version,
            terms_hash: v.terms_hash,
            requirementId: r.id,
            requirement_expected_version: r.version,
            proposed_kind: "PREFERENCE",
            ...f,
            expires_at: iso(f.expires_at),
          },
          "Clarification requested. No role terms were changed.",
        )
      }
    />
  );
}

const MEMBER_ROLES = ["RECRUITER", "HIRING_MANAGER"];
const PERMISSIONS = [
  [
    "ORG_ADMIN",
    "Manage organization details, ordinary team invitations and job opening capacity.",
  ],
  ["RECRUITER", "Create and edit job openings with assigned job opening access."],
  ["HIRING_MANAGER", "Review assigned job opening decisions and hiring processes."],
  [
    "AUTHORIZED_SIGNATORY",
    "Authorize exact policy terms and issue formal offers with independently approved authority.",
  ],
];

export function TeamPage() {
  const { data, execute } = useWorkspace();
  const [orgId, setOrgId] = useState("");
  const activeOrgId = orgId || data.organization.id;
  const invitation =
    data.backend.lastInvitation?.org_id === activeOrgId
      ? data.backend.lastInvitation
      : undefined;
  return (
    <>
      <PageHeader
        eyebrow={data.organization.name}
        title="Team & permissions"
        description="Database memberships and job opening access govern decisions. Privileged authority requires independent verification."
      />
      <div className="grid max-w-5xl gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex flex-col gap-6">
          <section className="panel flex flex-col gap-4 p-5">
            <Field>
              <FieldLabel htmlFor="team-org">Organization</FieldLabel>
              <select
                id="team-org"
                className={selectClass}
                value={activeOrgId}
                onChange={(e) => setOrgId(e.target.value)}
              >
                <option value="">Choose organization</option>
                {data.backend.organizations.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.display_name}
                  </option>
                ))}
              </select>
            </Field>
            {activeOrgId && (
              <ActionDialog
                trigger="Create invitation"
                title="Invite a team member"
                description="Invitations require manual delivery. Creating an invitation does not send an email."
                fields={[
                  {
                    name: "email",
                    label: "Invitee email",
                    type: "email",
                    maxLength: 320,
                  },
                  {
                    name: "role",
                    label: "Role",
                    value: "RECRUITER",
                    options: MEMBER_ROLES,
                  },
                ]}
                submitLabel="Create invitation"
                onSubmit={(f) =>
                  execute(
                    "team.invite",
                    {
                      orgId: activeOrgId,
                      email: String(f.email).trim().toLowerCase(),
                      role: f.role,
                    },
                    "Invitation created. Share its token securely with the intended recipient.",
                  )
                }
              />
            )}
          </section>
          {invitation && (
            <Alert>
              <UserPlus />
              <AlertTitle>Invitation ready for manual delivery</AlertTitle>
              <AlertDescription>
                Share this token securely with the intended recipient. They must
                sign in with the invited email.
                <Input
                  aria-label="Invitation token"
                  readOnly
                  value={invitation.token}
                  className="mt-3 font-mono text-xs"
                  onFocus={(e) => e.currentTarget.select()}
                />
                <span className="mt-2 block">
                  Expires {date(invitation.expires_at)}
                </span>
              </AlertDescription>
            </Alert>
          )}
          <ActionDialog
            trigger="Accept your invitation"
            title="Accept invitation"
            description="Sign in with the email address that received the invitation."
            fields={[
              {
                name: "token",
                label: "Invitation token",
                minLength: 20,
                maxLength: 200,
              },
            ]}
            submitLabel="Accept invitation"
            onSubmit={(f) =>
              execute("team.accept", { token: f.token }, "Invitation accepted.")
            }
          />
          <ul className="panel divide-y">
            {data.backend.memberships
              .filter((m) => m.org_id === activeOrgId)
              .map((m) => (
                <li
                  key={`${m.id}-${m.version}`}
                  className="flex flex-wrap items-center gap-4 p-4"
                >
                  <div className="min-w-0 flex-1">
                    <p className="break-all font-mono text-xs">
                      {m.user_id ?? m.id}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {human(m.status ?? "ACTIVE")}
                    </p>
                  </div>
                  <Badge variant="outline">{human(m.role)}</Badge>
                  {MEMBER_ROLES.includes(m.role) && m.version && (
                    <ActionDialog
                      trigger="Change role"
                      title="Change team role"
                      description="Privileged authority requires independent verification and cannot be granted here."
                      fields={[
                        {
                          name: "role",
                          label: "Role",
                          value: m.role,
                          options: MEMBER_ROLES,
                        },
                      ]}
                      onSubmit={(f) =>
                        execute(
                          "team.update",
                          {
                            orgId: activeOrgId,
                            id: m.id,
                            expected_version: m.version,
                            role: f.role,
                          },
                          "Team role updated.",
                        )
                      }
                    />
                  )}
                </li>
              ))}
          </ul>
        </div>
        <aside className="panel flex flex-col divide-y self-start">
          {PERMISSIONS.map(([role, description]) => (
            <div key={role} className="p-4">
              <p className="text-sm font-medium">{human(role)}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {description}
              </p>
            </div>
          ))}
        </aside>
      </div>
    </>
  );
}
