import type { ApiSchema } from "./workspace-types";

export const ONBOARDING_STEPS = [
  "About you",
  "Preferences",
  "Background",
  "Skills & resume",
  "Review",
] as const;
export const EMPLOYMENT_OPTIONS = [
  ["FULL_TIME", "Full time"],
  ["PART_TIME", "Part time"],
  ["CONTRACT", "Contract"],
  ["INTERNSHIP", "Internship"],
  ["TEMPORARY", "Temporary"],
] as const;
export const WORK_OPTIONS = [
  ["REMOTE", "Remote"],
  ["HYBRID", "Hybrid"],
  ["ONSITE", "On-site"],
] as const;
export const MAX_RESUME_BYTES = 4_000_000;

type SavedCandidate = ApiSchema["CandidateOut"];
export type ExperienceDraft = {
  title: string;
  organization_label: string;
  details: string;
  start_date: string;
  end_date: string;
  disclose_organization: boolean;
};
export type EducationDraft = {
  qualification: string;
  institution: string;
  details: string;
};
export type OnboardingDraft = {
  displayName: string;
  headline: string;
  summary: string;
  region: string;
  linkedin: string;
  portfolio: string;
  roles: string;
  locations: string;
  employmentTypes: string[];
  workModes: string[];
  compensation: string;
  currency: string;
  payPeriod: string;
  availableFrom: string;
  availableUntil: string;
  capacity: number;
  experiences: ExperienceDraft[];
  education: EducationDraft[];
  skills: string[];
  termsAccepted: boolean;
  privacyAccepted: boolean;
  profileConfirmed: boolean;
};
export const emptyExperience = (): ExperienceDraft => ({
  title: "",
  organization_label: "",
  details: "",
  start_date: "",
  end_date: "",
  disclose_organization: false,
});
export const emptyEducation = (): EducationDraft => ({
  qualification: "",
  institution: "",
  details: "",
});
export function labels(value: string): string[] {
  return [
    ...new Set(
      value
        .split(/[,\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}
export function onboardingDraft(
  candidate: SavedCandidate | null,
  skills: string[] = [],
): OnboardingDraft {
  return {
    displayName: candidate?.display_name || "",
    headline: candidate?.headline || "",
    summary: candidate?.summary || "",
    region: candidate?.region || "",
    linkedin: candidate?.professional_links?.linkedin || "",
    portfolio: candidate?.professional_links?.portfolio || "",
    roles: candidate?.role_families.join(", ") || "",
    locations: candidate?.locations.join(", ") || "",
    employmentTypes: candidate?.employment_types || ["FULL_TIME"],
    workModes: candidate?.work_modes || ["REMOTE"],
    compensation:
      candidate?.compensation_floor == null
        ? ""
        : String(candidate.compensation_floor),
    currency: candidate?.currency || "USD",
    payPeriod: candidate?.compensation_period || "ANNUAL",
    availableFrom: candidate?.available_from?.slice(0, 10) || "",
    availableUntil: candidate?.available_until?.slice(0, 10) || "",
    capacity: candidate?.cap || 3,
    experiences:
      candidate?.experiences.map((item) => ({
        ...item,
        end_date: item.end_date || "",
      })) || [],
    education: candidate?.education.map((item) => ({ ...item })) || [],
    skills,
    // Consent is deliberately reviewed again when a profile is edited.
    termsAccepted: false,
    privacyAccepted: false,
    profileConfirmed: false,
  };
}
function validDate(value: string) {
  const date = new Date(`${value}T00:00:00Z`);
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !value.startsWith("0000-") &&
    Number.isFinite(date.getTime()) &&
    date.toISOString().slice(0, 10) === value
  );
}
export function validProfessionalLink(
  value: string,
  linkedin = false,
): boolean {
  if (!value.trim()) return true;
  try {
    const url = new URL(value.trim());
    return (
      value.length <= 500 &&
      url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      (!linkedin ||
        (["linkedin.com", "www.linkedin.com"].includes(url.hostname) &&
          url.pathname.startsWith("/in/")))
    );
  } catch {
    return false;
  }
}
export function skillError(name: string): string | null {
  return name.length < 1 ||
    name.length > 100 ||
    !/^[\p{L}\p{N}_ .+#/-]+$/u.test(name)
    ? "Use a skill name of 1–100 characters, with letters, numbers, spaces, or . + # / -."
    : null;
}
export function onboardingErrors(
  draft: OnboardingDraft,
  step: number,
): string[] {
  const errors: string[] = [];
  if (step === 0) {
    if (draft.displayName.trim().length < 2 || draft.displayName.length > 120)
      errors.push("Enter the name you would like to use (2–120 characters).");
    if (draft.headline.trim().length < 3 || draft.headline.length > 180)
      errors.push("Enter a professional headline of 3–180 characters.");
    if (draft.region.trim().length < 2 || draft.region.length > 160)
      errors.push("Enter your city or region (2–160 characters).");
    if (draft.summary.length > 10000)
      errors.push("Keep your summary within 10,000 characters.");
    if (!validProfessionalLink(draft.linkedin, true))
      errors.push(
        "Use a public https://www.linkedin.com/in/… profile link, or leave it blank.",
      );
    if (!validProfessionalLink(draft.portfolio))
      errors.push(
        "Use an HTTPS portfolio link without a username or password, or leave it blank.",
      );
  }
  if (step === 1) {
    const roles = labels(draft.roles),
      locations = labels(draft.locations);
    if (
      !roles.length ||
      roles.length > 20 ||
      roles.some((item) => item.length > 120)
    )
      errors.push(
        "Add 1–20 desired role families, each within 120 characters.",
      );
    if (locations.length > 50 || locations.some((item) => item.length > 120))
      errors.push(
        "Use at most 50 preferred locations, each within 120 characters.",
      );
    if (
      !draft.employmentTypes.length ||
      draft.employmentTypes.some(
        (value) => !EMPLOYMENT_OPTIONS.some(([id]) => id === value),
      )
    )
      errors.push("Choose at least one employment type.");
    if (
      !draft.workModes.length ||
      draft.workModes.some(
        (value) => !WORK_OPTIONS.some(([id]) => id === value),
      )
    )
      errors.push("Choose at least one work arrangement.");
    if (
      draft.compensation &&
      (!/^\d{1,12}(\.\d{1,2})?$/.test(draft.compensation) ||
        !Number.isFinite(Number(draft.compensation)))
    )
      errors.push(
        "Enter a nonnegative compensation minimum with at most 12 digits and two decimals, or leave it blank.",
      );
    if (!/^[A-Z]{3}$/.test(draft.currency))
      errors.push("Use a three-letter currency code, such as USD.");
    if (!["ANNUAL", "MONTHLY", "HOURLY"].includes(draft.payPeriod))
      errors.push("Choose an annual, monthly, or hourly compensation period.");
    if (
      !Number.isInteger(draft.capacity) ||
      draft.capacity < 1 ||
      draft.capacity > 10
    )
      errors.push("Choose an active decision limit between 1 and 10.");
    if (draft.availableFrom && !validDate(draft.availableFrom))
      errors.push("Enter a valid availability start date.");
    if (draft.availableUntil && !validDate(draft.availableUntil))
      errors.push("Enter a valid availability end date.");
    if (
      draft.availableUntil &&
      (!draft.availableFrom || draft.availableUntil <= draft.availableFrom)
    )
      errors.push("Availability end must be later than its start.");
  }
  if (step === 2) {
    if (draft.experiences.length > 50 || draft.education.length > 30)
      errors.push("Use at most 50 experience and 30 education entries.");
    draft.experiences.forEach((item, index) => {
      if (
        item.title.trim().length < 2 ||
        item.title.length > 180 ||
        !item.organization_label.trim() ||
        item.organization_label.length > 180 ||
        item.details.length > 3000 ||
        !validDate(item.start_date) ||
        (item.end_date &&
          (!validDate(item.end_date) || item.end_date < item.start_date))
      )
        errors.push(
          `Complete experience ${index + 1}: role, organization, valid dates, and a description within 3,000 characters.`,
        );
    });
    draft.education.forEach((item, index) => {
      if (
        item.qualification.trim().length < 2 ||
        item.qualification.length > 180 ||
        item.institution.trim().length < 2 ||
        item.institution.length > 180 ||
        item.details.length > 2000
      )
        errors.push(
          `Complete education ${index + 1}: qualification, institution, and details within 2,000 characters.`,
        );
    });
  }
  if (
    step === 3 &&
    (draft.skills.length > 50 || draft.skills.some((name) => skillError(name)))
  )
    errors.push(
      "Use at most 50 valid skill names, each within 100 characters.",
    );
  if (
    step === 4 &&
    (!draft.termsAccepted || !draft.privacyAccepted || !draft.profileConfirmed)
  )
    errors.push("Review and confirm all three choices before saving.");
  return errors;
}
export function onboardingPayload(
  draft: OnboardingDraft,
  expectedVersion: number,
) {
  return {
    expected_version: expectedVersion,
    display_name: draft.displayName.trim(),
    headline: draft.headline.trim(),
    summary: draft.summary.trim(),
    region: draft.region.trim(),
    professional_links: {
      ...(draft.linkedin.trim() ? { linkedin: draft.linkedin.trim() } : {}),
      ...(draft.portfolio.trim() ? { portfolio: draft.portfolio.trim() } : {}),
    },
    role_families: labels(draft.roles),
    employment_types: draft.employmentTypes,
    work_modes: draft.workModes,
    locations: labels(draft.locations),
    compensation_floor: draft.compensation || null,
    currency: draft.currency,
    compensation_period: draft.payPeriod,
    cap: draft.capacity,
    experiences: draft.experiences.map((item) => ({
      ...item,
      title: item.title.trim(),
      organization_label: item.organization_label.trim(),
      details: item.details.trim(),
      end_date: item.end_date || null,
    })),
    education: draft.education.map((item) => ({
      ...item,
      qualification: item.qualification.trim(),
      institution: item.institution.trim(),
      details: item.details.trim(),
    })),
    available_from: draft.availableFrom
      ? `${draft.availableFrom}T00:00:00Z`
      : null,
    available_until: draft.availableUntil
      ? `${draft.availableUntil}T00:00:00Z`
      : null,
    terms_accepted: draft.termsAccepted,
    privacy_accepted: draft.privacyAccepted,
    profile_confirmed: draft.profileConfirmed,
  };
}
