import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const url = new URL("../lib/onboarding-chat.ts", import.meta.url);
const source = ts.transpileModule(readFileSync(url, "utf8"), {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const module = { exports: {} };
new Function("require", "module", "exports", source)(
  createRequire(url),
  module,
  module.exports,
);
const {
  onboardingDraft,
  validOnboardingDraft,
  parseOnboardingReply,
  pendingOnboarding,
  onboardingHistory,
  onboardingConfirmation,
  reviewErrors,
  onboardingAssistantTurn,
  onboardingIntroduction,
  onboardingSkipField,
} = module.exports;

function complete() {
  return {
    ...onboardingDraft(null),
    headline: "Electrical engineering",
    region: "Seattle",
    role_families: ["Engineering"],
    employment_types: ["FULL_TIME"],
    work_modes: ["REMOTE"],
    currency: "USD",
    compensation_period: "ANNUAL",
  };
}

test("display removes only an exact duplicated question and keeps complete history", () => {
  const result = reply().data;
  result.reply = `Let us look at Python. ${result.question.prompt}`;
  const original = result.reply;
  assert.equal(onboardingIntroduction(result), "Let us look at Python.");
  assert.equal(result.reply, original);
  assert.ok(onboardingAssistantTurn(result).content.includes(original));
  assert.equal(
    onboardingIntroduction({ ...result, reply: result.question.prompt }),
    "",
  );
  const different = result.question.prompt.replace("Rubric:", "Scoring:");
  assert.equal(
    onboardingIntroduction({ ...result, reply: different }),
    different,
  );
});
function reply(draft = complete()) {
  return {
    data: {
      reply: "Let us explore your experience.",
      question: {
        field: "skills",
        kind: "skill_probe",
        skill: "Python",
        prompt:
          "Python practice: explain a data validation step. Rubric: describe the rule, a test and an edge case.",
        choices: [],
      },
      draft,
      missing_fields: [],
      ready_for_review: false,
      version: 1,
    },
  };
}

test("private compensation and dates require separate sharing; source draft stays intact", () => {
  const draft = {
    ...complete(),
    compensation_floor: "95000",
    available_from: "2026-12-01T00:00:00Z",
  };
  const pending = pendingOnboarding(
    "Start my introduction",
    draft,
    [],
    "request-12345678",
  );
  const body = JSON.parse(pending.body);
  assert.equal(body.draft.compensation_floor, null);
  assert.equal(body.draft.available_from, null);
  assert.ok(body.draft.skipped_fields.includes("compensation"));
  assert.ok(body.draft.skipped_fields.includes("availability"));
  assert.equal(draft.compensation_floor, "95000");
  assert.equal(
    JSON.parse(
      pendingOnboarding("Start", draft, [], "other-12345678", true).body,
    ).draft.compensation_floor,
    "95000",
  );
  assert.equal(body.consent_to_gemini, true);
});

test("a pending retry owns an immutable serialized body and original key", () => {
  const draft = complete();
  const turns = [
    { role: "user", content: "Earlier question" },
    { role: "assistant", content: "Earlier answer" },
  ];
  const request = pendingOnboarding(
    "  A correction  ",
    draft,
    turns,
    "exact-key-12345678",
  );
  const original = request.body;
  draft.role_families.push("Changed later");
  turns[0].content = "Changed later";
  assert.equal(request.body, original);
  assert.equal(request.key, "exact-key-12345678");
  assert.equal(request.message, "A correction");
  assert.ok(Object.isFrozen(request));
});

test("history sends only whole completed pairs inside 20-entry and 24000-character limits", () => {
  const turns = Array.from({ length: 30 }, (_, i) => ({
    role: i % 2 ? "assistant" : "user",
    content: String(i).padStart(2000, "x"),
  }));
  const selected = onboardingHistory(turns);
  assert.equal(selected.length, 12);
  assert.equal(
    selected.reduce((n, x) => n + Array.from(x.content).length, 0),
    24000,
  );
  assert.deepEqual(selected[0], turns[18]);
  assert.deepEqual(
    onboardingHistory([...turns, { role: "user", content: "unfinished" }]),
    [],
  );
});

test("the new message shares the 24000-character budget with completed history", () => {
  const turns = Array.from({ length: 12 }, (_, i) => ({
    role: i % 2 ? "assistant" : "user",
    content: "x".repeat(2000),
  }));
  const request = JSON.parse(
    pendingOnboarding("y".repeat(2000), complete(), turns, "budget-12345678")
      .body,
  );
  assert.equal(request.history.length, 10);
  assert.ok(
    request.history.reduce(
      (size, turn) => size + Array.from(turn.content).length,
      Array.from(request.message).length,
    ) <= 24000,
  );
});

test("the named practice rubric survives long reply truncation and canonical skip avoids repeat probes", () => {
  const result = reply().data;
  result.reply = "x".repeat(4000);
  const turn = onboardingAssistantTurn(result);
  assert.equal(Array.from(turn.content).length, 4000);
  assert.ok(turn.content.startsWith(result.question.prompt));
  assert.ok(turn.content.includes("Rubric:"));
  assert.equal(
    onboardingSkipField({ ...result.question, skill: "  Data   Analysis " }),
    "skill:data analysis",
  );
});

test("unreviewed levels stay null and cannot silently become an intermediate level", () => {
  const draft = complete();
  draft.skills = [
    { name: "Python", level: null, evidence: "", assessment_note: "" },
  ];
  assert.ok(validOnboardingDraft(draft));
  assert.equal(parseOnboardingReply(reply(draft)).draft.skills[0].level, null);
  assert.throws(
    () => onboardingConfirmation(draft, null, 3),
    /Choose a self-reported level/,
  );
  assert.equal(
    parseOnboardingReply(
      reply({ ...draft, skills: [{ ...draft.skills[0], level: 6 }] }),
    ),
    null,
  );
  assert.equal(
    parseOnboardingReply({
      data: {
        ...reply().data,
        question: { ...reply().data.question, prompt: "No rubric supplied." },
      },
    }),
    null,
  );
});

test("review requires explicit nonremote locations and honors attention and availability boundaries", () => {
  assert.deepEqual(reviewErrors(complete(), 3), []);
  assert.match(
    reviewErrors({ ...complete(), work_modes: ["REMOTE", "HYBRID"] }, 3).join(
      " ",
    ),
    /explicit locations/,
  );
  assert.match(reviewErrors(complete(), 11).join(" "), /1 to 10/);
  assert.match(
    reviewErrors(
      {
        ...complete(),
        available_from: "2026-12-02T00:00:00Z",
        available_until: "2026-12-01T00:00:00Z",
      },
      3,
    ).join(" "),
    /follow its start/,
  );
  assert.ok(
    !validOnboardingDraft({
      ...complete(),
      compensation_floor: "1234567890123.00",
    }),
  );
  const duplicate = {
    ...complete(),
    skills: [
      { name: "Data Analysis", level: 2, evidence: "", assessment_note: "" },
      { name: "data   analysis", level: 3, evidence: "", assessment_note: "" },
    ],
  };
  assert.match(reviewErrors(duplicate, 3).join(" "), /duplicate skill/);
});

test("atomic confirmation preserves existing experience and education and reviewed version", () => {
  const candidate = {
    version: 7,
    experiences: [{ title: "Existing job" }],
    education: [{ institution: "Existing education" }],
  };
  const draft = complete();
  draft.skills = [
    {
      name: "Python",
      level: 2,
      evidence: "Practice example, kept private in page memory",
      assessment_note: "Self-reported suggestion",
    },
  ];
  const payload = onboardingConfirmation(draft, candidate, 4);
  assert.equal(payload.profile.expected_version, 7);
  assert.deepEqual(payload.profile.experiences, candidate.experiences);
  assert.deepEqual(payload.profile.education, candidate.education);
  assert.deepEqual(payload.skills, [{ name: "Python", level: 2 }]);
  assert.equal(payload.skills_confirmed, true);
  assert.equal(payload.profile.cap, 4);
  assert.doesNotMatch(
    JSON.stringify(payload),
    /Practice example|assessment_note/,
  );
});

test("a blank draft remains blank and carries no invented role, location or skill level", () => {
  const draft = onboardingDraft(null);
  assert.equal(draft.headline, null);
  assert.equal(draft.region, null);
  assert.deepEqual(draft.skills, []);
  assert.deepEqual(draft.role_families, []);
  assert.ok(reviewErrors(draft, 3).length);
});
