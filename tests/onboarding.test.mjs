import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";

const modules = new Map();
function load(url) {
  const filename = fileURLToPath(url);
  if (modules.has(filename)) return modules.get(filename).exports;
  const module = { exports: {} };
  modules.set(filename, module);
  const source = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: filename,
  }).outputText;
  const require = createRequire(url);
  new Function(
    "exports",
    "require",
    "module",
    "__filename",
    "__dirname",
    source,
  )(
    module.exports,
    (name) =>
      name.startsWith(".") ? load(new URL(`${name}.ts`, url)) : require(name),
    module,
    filename,
    dirname(filename),
  );
  return module.exports;
}
const {
  onboardingDraft,
  onboardingPayload,
  onboardingErrors,
  validProfessionalLink,
  skillError,
  MAX_RESUME_BYTES,
} = load(new URL("../lib/onboarding.ts", import.meta.url));
const { resumeForm } = load(
  new URL("../lib/server/resume-upload.ts", import.meta.url),
);
const { Backend } = load(new URL("../lib/server/backend.ts", import.meta.url));
const { workspaceCommand } = load(
  new URL("../lib/server/workspace-commands.ts", import.meta.url),
);
const { onboardingSaveState, saveOnboarding } = load(
  new URL("../lib/onboarding-save.ts", import.meta.url),
);

function draft() {
  return {
    ...onboardingDraft(null),
    displayName: "Test Candidate",
    headline: "Software developer",
    region: "Seattle",
    roles: "Software engineering, Product engineering",
    termsAccepted: true,
    privacyAccepted: true,
    profileConfirmed: true,
  };
}
test("complete onboarding maps actual career information with private preferences and explicit consent", () => {
  const value = {
    ...draft(),
    linkedin: "https://www.linkedin.com/in/test-fixture",
    portfolio: "https://portfolio.example",
    compensation: "0",
    availableFrom: "2027-01-01",
    availableUntil: "2027-02-01",
    locations: "Seattle, Seattle\nPortland",
    experiences: [
      {
        title: "Developer",
        organization_label: "Test organization",
        start_date: "2024-01-01",
        end_date: "",
        details: "Built useful tools",
        disclose_organization: false,
      },
    ],
    education: [
      {
        qualification: "Computing certificate",
        institution: "Test institution",
        details: "",
      },
    ],
  };
  for (let step = 0; step < 5; step++)
    assert.deepEqual(onboardingErrors(value, step), []);
  const result = onboardingPayload(value, 8);
  assert.equal(result.expected_version, 8);
  assert.equal(result.display_name, "Test Candidate");
  assert.deepEqual(result.professional_links, {
    linkedin: value.linkedin,
    portfolio: value.portfolio,
  });
  assert.deepEqual(result.locations, ["Seattle", "Portland"]);
  assert.equal(result.compensation_floor, "0");
  assert.equal(result.experiences[0].end_date, null);
  assert.equal(result.experiences[0].disclose_organization, false);
  assert.equal(result.available_from, "2027-01-01T00:00:00Z");
  assert.equal(result.available_until, "2027-02-01T00:00:00Z");
  assert.equal(result.profile_confirmed, true);
});
test("existing information is restored without assuming renewed consent or compensation", () => {
  const input = {
    ...onboardingPayload(draft(), 0),
    id: "test",
    version: 4,
    compensation_floor: null,
    available_from: null,
    available_until: null,
    experiences: [],
    education: [],
    terms_accepted: true,
    privacy_accepted: true,
  };
  const restored = onboardingDraft(input, ["Python"]);
  assert.equal(restored.displayName, "Test Candidate");
  assert.equal(restored.compensation, "");
  assert.deepEqual(restored.skills, ["Python"]);
  assert.equal(restored.termsAccepted, false);
  assert.equal(restored.privacyAccepted, false);
  assert.equal(restored.profileConfirmed, false);
  assert.ok(onboardingErrors(restored, 4).length);
  assert.deepEqual(onboardingErrors(restored, 2), []);
  assert.equal(onboardingPayload(restored, 4).compensation_floor, null);
});
test("career validation rejects invalid dates, reversed availability and absent work choices", () => {
  assert.ok(
    onboardingErrors({ ...draft(), availableFrom: "2026-99-99" }, 1).length,
  );
  assert.ok(
    onboardingErrors({ ...draft(), availableFrom: "2026-02-30" }, 1).length,
  );
  assert.ok(
    onboardingErrors({ ...draft(), availableFrom: "0000-01-01" }, 1).length,
  );
  assert.ok(
    onboardingErrors(
      { ...draft(), availableFrom: "2026-10-10", availableUntil: "2026-10-09" },
      1,
    ).length,
  );
  assert.ok(
    onboardingErrors({ ...draft(), availableUntil: "2026-10-10" }, 1).length,
  );
  assert.ok(
    onboardingErrors({ ...draft(), employmentTypes: [], workModes: [] }, 1)
      .length >= 2,
  );
  assert.ok(onboardingErrors({ ...draft(), compensation: "-1" }, 1).length);
  assert.ok(onboardingErrors({ ...draft(), compensation: "1.001" }, 1).length);
  assert.ok(
    onboardingErrors({ ...draft(), compensation: "1234567890123" }, 1).length,
  );
  assert.ok(
    onboardingErrors(
      {
        ...draft(),
        experiences: [
          {
            title: "Developer",
            organization_label: "Org",
            start_date: "2026-02-30",
            end_date: "",
            details: "",
            disclose_organization: false,
          },
        ],
      },
      2,
    ).length,
  );
});
test("professional links never accept active schemes, credentials, or a pretend LinkedIn host", () => {
  assert.equal(validProfessionalLink(""), true);
  for (const link of [
    "javascript:alert(1)",
    "http://portfolio.example",
    "https://user:secret@portfolio.example",
  ])
    assert.equal(validProfessionalLink(link), false);
  assert.equal(
    validProfessionalLink(
      "https://linkedin.com.attacker.example/in/person",
      true,
    ),
    false,
  );
  assert.equal(
    validProfessionalLink("https://www.linkedin.com/company/example", true),
    false,
  );
  assert.equal(
    validProfessionalLink("https://www.linkedin.com/in/person", true),
    true,
  );
  assert.equal(skillError("C++"), null);
  assert.equal(skillError("C#"), null);
  assert.equal(skillError("Communication"), null);
  assert.ok(skillError("<script>"));
});
test("candidate gateway persists new basic fields and only maps supported candidate information", async () => {
  const calls = [];
  const api = {
    async request(path, options) {
      calls.push({ path, ...options });
      return { data: { version: 1 } };
    },
  };
  await workspaceCommand(
    api,
    "candidate.save",
    {
      ...onboardingPayload(draft(), 0),
      admin: true,
      password: "never forwarded",
    },
    "onboarding-test",
  );
  assert.equal(calls[0].path, "/v1/candidates/me");
  assert.equal(calls[0].body.display_name, "Test Candidate");
  assert.deepEqual(calls[0].body.professional_links, {});
  assert.equal(Object.hasOwn(calls[0].body, "admin"), false);
  assert.equal(Object.hasOwn(calls[0].body, "password"), false);
  assert.equal(calls[0].key, "onboarding-test");
});
function upload(file, extras = false) {
  const body = new FormData();
  body.set("file", file);
  if (extras) body.set("untrusted", "extra field");
  return new Request("https://career.example/api/workspace/resume", {
    method: "POST",
    body,
  });
}
test("resume proxy bounds file size, accepts text and replaces the private original filename", async () => {
  const outgoing = await resumeForm(
    upload(
      new File(["Career summary"], "private-name.txt", { type: "text/plain" }),
    ),
  );
  assert.equal(outgoing.get("file").name, "resume.txt");
  assert.equal(outgoing.get("file").type, "text/plain");
  assert.equal(await outgoing.get("file").text(), "Career summary");
  await assert.rejects(
    resumeForm(upload(new File([""], "resume.txt", { type: "text/plain" }))),
    (error) => error.status === 413,
  );
  await assert.rejects(
    resumeForm(
      upload(new File(["binary"], "resume.pdf", { type: "application/pdf" })),
    ),
    (error) => error.status === 415,
  );
  await assert.rejects(
    resumeForm(
      upload(new File(["text"], "resume.txt", { type: "text/plain" }), true),
    ),
    (error) => error.status === 422,
  );
  await assert.rejects(
    resumeForm(
      upload(
        new File([new Uint8Array(MAX_RESUME_BYTES + 1)], "resume.txt", {
          type: "text/plain",
        }),
      ),
    ),
    (error) => error.status === 413,
  );
});
test("oversized chunked uploads are stopped before multipart parsing without relying on Content-Length", async () => {
  let canceled = false;
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array(MAX_RESUME_BYTES + 32_001));
    },
    cancel() {
      canceled = true;
    },
  });
  const request = new Request("https://career.example/api/workspace/resume", {
    method: "POST",
    headers: { "Content-Type": "multipart/form-data; boundary=test" },
    body: stream,
    duplex: "half",
  });
  await assert.rejects(resumeForm(request), (error) => error.status === 413);
  assert.equal(canceled, true);
});
test("backend multipart uses server authentication and idempotency while allowing a real multipart boundary", async () => {
  const previousFetch = globalThis.fetch,
    previousBase = process.env.CAREER_KITCHEN_API_URL;
  const body = new FormData();
  body.set("file", new File(["test"], "resume.txt", { type: "text/plain" }));
  try {
    process.env.CAREER_KITCHEN_API_URL = "https://api.example";
    globalThis.fetch = async (url, options) => {
      assert.equal(url, "https://api.example/v1/candidates/me/resume");
      assert.equal(
        options.headers.Authorization,
        "Bearer fictional-server-token",
      );
      assert.equal(options.headers["Idempotency-Key"], "resume-test-operation");
      assert.equal(Object.hasOwn(options.headers, "Content-Type"), false);
      assert.equal(options.body, body);
      assert.equal(options.redirect, "error");
      return Response.json({ data: { candidate_version: 2 } });
    };
    const result = await new Backend("fictional-server-token").request(
      "/v1/candidates/me/resume",
      { method: "POST", key: "resume-test-operation", body },
    );
    assert.equal(result.data.candidate_version, 2);
  } finally {
    globalThis.fetch = previousFetch;
    if (previousBase === undefined) delete process.env.CAREER_KITCHEN_API_URL;
    else process.env.CAREER_KITCHEN_API_URL = previousBase;
  }
});

function saveOperations(overrides = {}) {
  let nextKey = 0;
  return {
    async saveProfile(payload) {
      return { version: payload.expected_version + 1 };
    },
    async addSkill(name) {
      return {
        id: `skill-${name}`,
        name,
        version: 1,
        level: 3,
        verification_status: "SELF_REPORTED",
      };
    },
    async removeSkill() {},
    async uploadResume() {
      return { candidate_version: 2 };
    },
    newKey: () => `resume-operation-${++nextKey}`,
    status() {},
    ...overrides,
  };
}
test("a lost resume response retries its original operation without rewriting the confirmed profile", async () => {
  const state = onboardingSaveState(0, []),
    value = draft(),
    file = new File(["Test resume"], "resume.txt", { type: "text/plain" });
  let profileCalls = 0,
    uploadCalls = 0,
    uploadWrites = 0;
  const committed = new Map(),
    keys = [];
  const operations = saveOperations({
    async saveProfile(payload) {
      profileCalls++;
      return { version: payload.expected_version + 1 };
    },
    async uploadResume(actualFile, key) {
      assert.equal(actualFile, file);
      keys.push(key);
      uploadCalls++;
      if (!committed.has(key)) {
        uploadWrites++;
        committed.set(key, { candidate_version: 2 });
        throw new TypeError("Response lost after commit");
      }
      return committed.get(key);
    },
  });
  await assert.rejects(
    saveOnboarding(value, file, state, operations),
    /Response lost/,
  );
  assert.equal(state.candidateVersion, 1);
  assert.ok(state.pendingResume);
  await saveOnboarding(value, file, state, operations);
  assert.equal(profileCalls, 1);
  assert.equal(uploadCalls, 2);
  assert.equal(uploadWrites, 1);
  assert.equal(keys[0], keys[1]);
  assert.equal(state.candidateVersion, 2);
  assert.equal(state.pendingResume, null);
});
test("edits after an uncertain upload recover the old result before saving with its new candidate version", async () => {
  const state = onboardingSaveState(0, []),
    value = draft(),
    file = new File(["Resume"], "resume.txt", { type: "text/plain" });
  const versions = [],
    order = [];
  let uploads = 0;
  const operations = saveOperations({
    async saveProfile(payload) {
      versions.push(payload.expected_version);
      order.push(`profile:${payload.expected_version}`);
      return { version: payload.expected_version + 1 };
    },
    async uploadResume() {
      uploads++;
      order.push("resume");
      if (uploads === 1) throw new TypeError("Lost response");
      return { candidate_version: 2 };
    },
  });
  await assert.rejects(
    saveOnboarding(value, file, state, operations),
    /Lost response/,
  );
  await saveOnboarding(
    { ...value, headline: "Updated professional headline" },
    null,
    state,
    operations,
  );
  assert.deepEqual(versions, [0, 2]);
  assert.deepEqual(order, ["profile:0", "resume", "resume", "profile:2"]);
  assert.equal(state.candidateVersion, 3);
});
test("unconfirmed profile and skill writes recover before later edits, without losing skill removal intent", async () => {
  const state = onboardingSaveState(0, []),
    value = { ...draft(), skills: ["Python"] };
  const profiles = [],
    skills = [],
    removed = [];
  let profileFailure = true,
    skillFailure = true;
  const operations = saveOperations({
    async saveProfile(payload) {
      profiles.push(payload);
      if (profileFailure) {
        profileFailure = false;
        throw new TypeError("Profile response lost");
      }
      return { version: payload.expected_version + 1 };
    },
    async addSkill(name) {
      skills.push(name);
      if (skillFailure) {
        skillFailure = false;
        throw new TypeError("Skill response lost");
      }
      return { id: "skill-1", name: name.toLowerCase(), version: 1 };
    },
    async removeSkill(skill) {
      removed.push(skill.id);
    },
  });
  await assert.rejects(
    saveOnboarding(value, null, state, operations),
    /Profile response lost/,
  );
  await assert.rejects(
    saveOnboarding(value, null, state, operations),
    /Skill response lost/,
  );
  await saveOnboarding({ ...value, skills: [] }, null, state, operations);
  assert.deepEqual(profiles[0], profiles[1]);
  assert.equal(profiles.length, 2);
  assert.deepEqual(skills, ["Python", "Python"]);
  assert.deepEqual(removed, ["skill-1"]);
  assert.equal(state.skills.size, 0);
});
test("a confirmed resume validation rejection can be corrected or removed without an endless retry", async () => {
  const state = onboardingSaveState(0, []),
    value = draft(),
    file = new File(["Bad text"], "resume.txt", { type: "text/plain" });
  let uploadCalls = 0;
  const operations = saveOperations({
    async uploadResume() {
      uploadCalls++;
      throw Object.assign(new Error("Invalid text"), { status: 422 });
    },
  });
  await assert.rejects(
    saveOnboarding(value, file, state, operations),
    /Invalid text/,
  );
  assert.equal(state.pendingResume, null);
  await saveOnboarding(value, null, state, operations);
  assert.equal(uploadCalls, 1);
});

test("server casefolding never makes onboarding remove a skill it just added", async () => {
  const state = onboardingSaveState(0, []),
    value = { ...draft(), skills: ["Straße"] };
  const removed = [];
  let additions = 0;
  const operations = saveOperations({
    async addSkill() {
      additions++;
      return { id: "skill-casefolded", name: "strasse", version: 1 };
    },
    async removeSkill(skill) {
      removed.push(skill.id);
    },
  });
  await saveOnboarding(value, null, state, operations);
  assert.equal(state.skills.size, 1);
  assert.deepEqual(removed, []);
  await saveOnboarding(
    { ...value, skills: ["strasse"] },
    null,
    state,
    operations,
  );
  assert.equal(additions, 1);
  assert.equal(state.skills.size, 1);
  await saveOnboarding({ ...value, skills: [] }, null, state, operations);
  assert.deepEqual(removed, ["skill-casefolded"]);
  assert.equal(state.skills.size, 0);
});

function clientCommands() {
  // Exercise the actual fetch function; its React hooks are not mounted here.
  const url = new URL("../lib/workspace.ts", import.meta.url),
    filename = fileURLToPath(url);
  const module = { exports: {} };
  const source = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: filename,
  }).outputText;
  new Function("exports", "require", "module", source)(
    module.exports,
    (name) => (name.startsWith(".") ? load(new URL(`${name}.ts`, url)) : {}),
    module,
  );
  return module.exports;
}
test("a truncated successful command response retains its idempotency key until the result is confirmed", async () => {
  const { sendWorkspaceCommand } = clientCommands(),
    previousFetch = globalThis.fetch;
  const keys = [];
  try {
    globalThis.fetch = async (_url, options) => {
      keys.push(options.headers["Idempotency-Key"]);
      return keys.length === 1
        ? new Response('{"data":', {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        : Response.json({ data: { version: 1 } });
    };
    await assert.rejects(
      sendWorkspaceCommand("candidate.save", { expected_version: 0 }),
      (error) => error.status === 503 && error.code === "UNCONFIRMED_RESPONSE",
    );
    assert.deepEqual(
      await sendWorkspaceCommand("candidate.save", { expected_version: 0 }),
      { version: 1 },
    );
    assert.equal(keys[0], keys[1]);
    await sendWorkspaceCommand("candidate.save", { expected_version: 0 });
    assert.notEqual(keys[1], keys[2]);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
test("missing success envelopes remain uncertain while confirmed input rejections release their operation key", async () => {
  const { sendWorkspaceCommand } = clientCommands(),
    previousFetch = globalThis.fetch;
  const keys = [];
  let response = Response.json({});
  try {
    globalThis.fetch = async (_url, options) => {
      keys.push(options.headers["Idempotency-Key"]);
      return response;
    };
    await assert.rejects(
      sendWorkspaceCommand("candidate.save", { expected_version: 0 }),
      (error) => error.status === 503,
    );
    response = Response.json(
      { error: { code: "INVALID_PROFILE", message: "Correct the profile" } },
      { status: 422 },
    );
    await assert.rejects(
      sendWorkspaceCommand("candidate.save", { expected_version: 0 }),
      (error) => error.status === 422,
    );
    assert.equal(keys[0], keys[1]);
    response = Response.json({ data: { version: 1 } });
    await sendWorkspaceCommand("candidate.save", { expected_version: 0 });
    assert.notEqual(keys[1], keys[2]);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
