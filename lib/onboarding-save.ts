import { onboardingPayload, type OnboardingDraft } from "./onboarding";
import type { ApiSchema } from "./workspace-types";

type Skill = ApiSchema["SkillOut"];
type ProfilePayload = ReturnType<typeof onboardingPayload>;
export type OnboardingSaveState = {
  candidateVersion: number;
  profileFingerprint: string | null;
  hasSavedProfile: boolean;
  skills: Map<string, Skill>;
  pendingProfile: { payload: ProfilePayload; fingerprint: string } | null;
  pendingSkill:
    | { kind: "add"; name: string }
    | { kind: "remove"; skill: Skill; key: string }
    | null;
  pendingResume: { file: File; key: string } | null;
  uploadedResume: File | null;
};
export function onboardingSaveState(
  version: number,
  skills: Skill[],
): OnboardingSaveState {
  return {
    candidateVersion: version,
    profileFingerprint: null,
    hasSavedProfile: false,
    skills: new Map(skills.map((skill) => [skill.name.toLowerCase(), skill])),
    pendingProfile: null,
    pendingSkill: null,
    pendingResume: null,
    uploadedResume: null,
  };
}
type Operations = {
  saveProfile: (payload: ProfilePayload) => Promise<{ version: number }>;
  addSkill: (name: string) => Promise<Skill>;
  removeSkill: (skill: Skill) => Promise<unknown>;
  uploadResume: (
    file: File,
    key: string,
  ) => Promise<{ candidate_version: number }>;
  newKey: () => string;
  status: (message: string) => void;
};
function knownRejection(error: unknown) {
  const status =
    error && typeof error === "object" && "status" in error
      ? Number(error.status)
      : 0;
  return status >= 400 && status < 500;
}

/** Keep unconfirmed operations so a retry can recover their original idempotent result.
 * A confirmed profile is not rewritten just to retry a skill or resume upload.
 */
export async function saveOnboarding(
  draft: OnboardingDraft,
  resume: File | null,
  state: OnboardingSaveState,
  operations: Operations,
): Promise<void> {
  async function profile() {
    if (!state.pendingProfile) return;
    operations.status("Saving your profile and preferences…");
    try {
      const result = await operations.saveProfile(state.pendingProfile.payload);
      state.candidateVersion = result.version;
      state.profileFingerprint = state.pendingProfile.fingerprint;
      state.hasSavedProfile = true;
      state.pendingProfile = null;
    } catch (error) {
      if (knownRejection(error)) state.pendingProfile = null;
      throw error;
    }
  }
  async function skill() {
    if (!state.pendingSkill) return;
    operations.status("Your profile is saved. Saving your skills…");
    try {
      if (state.pendingSkill.kind === "add") {
        const result = await operations.addSkill(state.pendingSkill.name);
        // Keep the requested spelling as an intent key: Python casefold can
        // return a different name (for example Straße -> strasse).
        state.skills.set(state.pendingSkill.name.toLowerCase(), result);
      } else {
        await operations.removeSkill(state.pendingSkill.skill);
        state.skills.delete(state.pendingSkill.key);
      }
      state.pendingSkill = null;
    } catch (error) {
      if (knownRejection(error)) state.pendingSkill = null;
      throw error;
    }
  }
  async function upload() {
    if (!state.pendingResume) return;
    operations.status(
      "Your profile and skills are saved. Confirming your private resume upload…",
    );
    try {
      const result = await operations.uploadResume(
        state.pendingResume.file,
        state.pendingResume.key,
      );
      state.candidateVersion = result.candidate_version;
      state.uploadedResume = state.pendingResume.file;
      state.pendingResume = null;
    } catch (error) {
      if (knownRejection(error)) state.pendingResume = null;
      throw error;
    }
  }

  // Resolve uncertain earlier writes before applying edits made after a failure.
  await profile();
  await skill();
  await upload();
  const fingerprint = JSON.stringify(onboardingPayload(draft, 0));
  if (state.profileFingerprint !== fingerprint) {
    state.pendingProfile = {
      payload: onboardingPayload(draft, state.candidateVersion),
      fingerprint,
    };
    await profile();
  }
  for (const name of draft.skills) {
    if (
      ![...state.skills].some(
        ([key, current]) =>
          key === name.toLowerCase() ||
          current.name.toLowerCase() === name.toLowerCase(),
      )
    ) {
      state.pendingSkill = { kind: "add", name };
      await skill();
    }
  }
  for (const [key, current] of state.skills) {
    if (
      !draft.skills.some(
        (name) =>
          name.toLowerCase() === key ||
          name.toLowerCase() === current.name.toLowerCase(),
      )
    ) {
      state.pendingSkill = { kind: "remove", skill: current, key };
      await skill();
    }
  }
  if (resume && resume !== state.uploadedResume) {
    state.pendingResume = { file: resume, key: operations.newKey() };
    await upload();
  }
  operations.status("Your profile, preferences, and skills are saved.");
}
