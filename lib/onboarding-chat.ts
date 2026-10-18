import type { ApiSchema } from "./workspace-types";

export type SkillSuggestion = {
  name: string;
  level: number | null;
  evidence: string;
  assessment_note: string;
};
export type OnboardingDraft = {
  headline: string | null;
  region: string | null;
  role_families: string[];
  employment_types: string[];
  work_modes: string[];
  locations: string[];
  compensation_floor: string | null;
  currency: string | null;
  compensation_period: "ANNUAL" | "MONTHLY" | "HOURLY" | null;
  skills: SkillSuggestion[];
  summary: string;
  available_from: string | null;
  available_until: string | null;
  skipped_fields: string[];
};
export type OnboardingTurn = { role: "user" | "assistant"; content: string };
export type OnboardingReply = {
  reply: string;
  question: {
    field: string;
    kind: "preference" | "skill_probe" | "clarification" | "review";
    prompt: string;
    skill?: string | null;
    choices: string[];
  };
  draft: OnboardingDraft;
  missing_fields: string[];
  ready_for_review: boolean;
  version: 1;
};
export type PendingOnboarding = Readonly<{
  key: string;
  body: string;
  message: string;
}>;

const employment = new Set([
  "FULL_TIME",
  "PART_TIME",
  "CONTRACT",
  "INTERNSHIP",
  "TEMPORARY",
]);
const modes = new Set(["REMOTE", "HYBRID", "ONSITE"]);
const periods = new Set(["ANNUAL", "MONTHLY", "HOURLY"]);
const text = (value: unknown, max: number): value is string =>
  typeof value === "string" && Array.from(value).length <= max;
const labels = (value: unknown, max = 50): value is string[] =>
  Array.isArray(value) &&
  value.length <= max &&
  value.every((x) => text(x, 120) && !!x.trim());

export function onboardingDraft(
  candidate: ApiSchema["CandidateOut"] | null,
  skills: ApiSchema["SkillOut"][] = [],
): OnboardingDraft {
  return {
    headline: candidate?.headline ?? null,
    region: candidate?.region ?? null,
    role_families: [...(candidate?.role_families ?? [])],
    employment_types: [...(candidate?.employment_types ?? [])],
    work_modes: [...(candidate?.work_modes ?? [])],
    locations: [...(candidate?.locations ?? [])],
    compensation_floor: candidate?.compensation_floor ?? null,
    currency: candidate?.currency ?? null,
    compensation_period:
      (candidate?.compensation_period as OnboardingDraft["compensation_period"]) ??
      null,
    summary: candidate?.summary ?? "",
    available_from: candidate?.available_from ?? null,
    available_until: candidate?.available_until ?? null,
    skipped_fields: [],
    skills: skills.slice(0, 8).map((skill) => ({
      name: skill.name,
      level: skill.level,
      evidence: "",
      assessment_note: "Existing self-reported skill.",
    })),
  };
}

export function validOnboardingDraft(value: unknown): value is OnboardingDraft {
  if (!value || typeof value !== "object") return false;
  const d = value as OnboardingDraft;
  return (
    (d.headline === null || text(d.headline, 180)) &&
    (d.region === null || text(d.region, 160)) &&
    labels(d.role_families, 20) &&
    labels(d.employment_types, 5) &&
    d.employment_types.every((x) => employment.has(x)) &&
    labels(d.work_modes, 3) &&
    d.work_modes.every((x) => modes.has(x)) &&
    labels(d.locations) &&
    (d.compensation_floor === null ||
      (text(d.compensation_floor, 15) &&
        /^\d{1,12}(\.\d{1,2})?$/.test(d.compensation_floor))) &&
    (d.currency === null ||
      (text(d.currency, 3) && /^[A-Z]{3}$/.test(d.currency))) &&
    (d.compensation_period === null || periods.has(d.compensation_period)) &&
    text(d.summary, 10000) &&
    [d.available_from, d.available_until].every(
      (x) =>
        x === null ||
        (text(x, 60) &&
          Number.isFinite(Date.parse(x)) &&
          /(?:Z|[+-]\d{2}:\d{2})$/.test(x)),
    ) &&
    labels(d.skipped_fields, 30) &&
    Array.isArray(d.skills) &&
    d.skills.length <= 8 &&
    d.skills.every(
      (s) =>
        s &&
        text(s.name, 100) &&
        !!s.name.trim() &&
        (s.level === null ||
          (Number.isInteger(s.level) && s.level >= 1 && s.level <= 5)) &&
        text(s.evidence, 2000) &&
        text(s.assessment_note, 2000),
    )
  );
}

export function parseOnboardingReply(value: unknown): OnboardingReply | null {
  if (
    !value ||
    typeof value !== "object" ||
    !("data" in value) ||
    !value.data ||
    typeof value.data !== "object"
  )
    return null;
  const d = value.data as OnboardingReply;
  if (
    d.version !== 1 ||
    !text(d.reply, 4000) ||
    !d.reply.trim() ||
    !validOnboardingDraft(d.draft) ||
    !labels(d.missing_fields, 30) ||
    typeof d.ready_for_review !== "boolean"
  )
    return null;
  const q = d.question;
  if (
    !q ||
    !text(q.field, 120) ||
    !text(q.prompt, 1800) ||
    !q.prompt.trim() ||
    !["preference", "skill_probe", "clarification", "review"].includes(
      q.kind,
    ) ||
    !Array.isArray(q.choices) ||
    q.choices.length > 6 ||
    !q.choices.every((x) => text(x, 120) && !!x.trim()) ||
    (q.skill != null && !text(q.skill, 100))
  )
    return null;
  if (q.kind === "skill_probe" && (!q.skill || !q.prompt.includes("Rubric:")))
    return null;
  return d;
}

export function onboardingSkipField(
  question: OnboardingReply["question"],
): string {
  return question.kind === "skill_probe" && question.skill
    ? `skill:${canonicalSkill(question.skill)}`
    : question.field;
}

const canonicalSkill = (value: string) =>
  value
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase()
    .replaceAll("ß", "ss")
    .replaceAll("ς", "σ");

/** Only completed pairs enter model context. Failed/pending requests never do. */
export function onboardingHistory(
  turns: OnboardingTurn[],
  message = "",
): OnboardingTurn[] {
  const history: OnboardingTurn[] = [];
  let length = Array.from(message).length;
  for (
    let index = turns.length - 2;
    index >= 0 && history.length < 20;
    index -= 2
  ) {
    const user = turns[index],
      assistant = turns[index + 1];
    if (user.role !== "user" || assistant.role !== "assistant") break;
    const size =
      Array.from(user.content).length + Array.from(assistant.content).length;
    if (length + size > 24000) break;
    history.unshift({ ...user }, { ...assistant });
    length += size;
  }
  return history;
}

export function pendingOnboarding(
  message: string,
  draft: OnboardingDraft,
  turns: OnboardingTurn[],
  key: string,
  sharePrivatePreferences = false,
): PendingOnboarding {
  const clean = message.trim();
  if (!clean || Array.from(clean).length > 2000)
    throw new Error("Use between 1 and 2,000 characters.");
  if (!validOnboardingDraft(draft))
    throw new Error(
      "Review incomplete draft fields before sending them to Career Chef.",
    );
  const shared = sharePrivatePreferences
    ? draft
    : {
        ...draft,
        compensation_floor: null,
        available_from: null,
        available_until: null,
        skipped_fields: Array.from(
          new Set([...draft.skipped_fields, "compensation", "availability"]),
        ),
      };
  return Object.freeze({
    key,
    message: clean,
    body: JSON.stringify({
      message: clean,
      consent_to_gemini: true,
      history: onboardingHistory(turns, clean),
      draft: shared,
    }),
  });
}

export function onboardingAssistantTurn(
  result: OnboardingReply,
): OnboardingTurn {
  // Preserve the named practice prompt and its rubric inside the per-entry
  // history limit; only the explanatory reply may be shortened.
  const prompt = result.question.prompt;
  const remaining = Math.max(0, 4000 - Array.from(prompt).length - 2);
  return {
    role: "assistant",
    content: `${prompt}\n\n${Array.from(result.reply).slice(0, remaining).join("")}`,
  };
}

/** The structured prompt is rendered once; retain the original reply in history. */
export function onboardingIntroduction(result: OnboardingReply): string {
  return result.reply.replace(result.question.prompt, "").trim();
}

export function reviewErrors(draft: OnboardingDraft, cap: number): string[] {
  const errors: string[] = [];
  if (!validOnboardingDraft(draft))
    errors.push("Check the profile values and skill suggestions.");
  if (!draft.headline || draft.headline.trim().length < 3)
    errors.push("Enter a headline of at least 3 characters.");
  if (!draft.region || draft.region.trim().length < 2)
    errors.push("Enter your region.");
  if (
    !draft.role_families.length ||
    !draft.employment_types.length ||
    !draft.work_modes.length
  )
    errors.push(
      "Choose role families, employment types and work arrangements.",
    );
  if (
    draft.work_modes.some((mode) => mode === "ONSITE" || mode === "HYBRID") &&
    !draft.locations.length
  )
    errors.push("Choose explicit locations for hybrid or onsite work.");
  if (!draft.currency || !draft.compensation_period)
    errors.push("Choose your currency and compensation period.");
  if (!Number.isInteger(cap) || cap < 1 || cap > 10)
    errors.push("Choose an attention capacity from 1 to 10.");
  if (draft.skills.some((s) => s.level === null))
    errors.push("Choose a self-reported level for every skill, or remove it.");
  if (
    draft.available_from &&
    draft.available_until &&
    Date.parse(draft.available_from) >= Date.parse(draft.available_until)
  )
    errors.push("Availability end must follow its start.");
  if (
    new Set(draft.skills.map((s) => canonicalSkill(s.name))).size !==
    draft.skills.length
  )
    errors.push("Combine duplicate skill names before confirming.");
  return errors;
}

export function onboardingConfirmation(
  draft: OnboardingDraft,
  candidate: ApiSchema["CandidateOut"] | null,
  cap: number,
) {
  const errors = reviewErrors(draft, cap);
  if (errors.length) throw new Error(errors.join(" "));
  return {
    profile: {
      expected_version: candidate?.version ?? 0,
      headline: draft.headline!.trim(),
      summary: draft.summary,
      region: draft.region!.trim(),
      role_families: draft.role_families,
      employment_types: draft.employment_types,
      work_modes: draft.work_modes,
      locations: draft.locations,
      compensation_floor: draft.compensation_floor,
      currency: draft.currency,
      compensation_period: draft.compensation_period,
      cap,
      experiences: candidate?.experiences ?? [],
      education: candidate?.education ?? [],
      available_from: draft.available_from,
      available_until: draft.available_until,
      terms_accepted: true,
      privacy_accepted: true,
      profile_confirmed: true,
    },
    skills: draft.skills.map((s) => ({ name: s.name.trim(), level: s.level })),
    skills_confirmed: true,
  };
}
