import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const cache = new Map();
function load(url) {
  if (cache.has(String(url))) return cache.get(String(url)).exports;
  const module = { exports: {} };
  cache.set(String(url), module);
  const source = ts.transpileModule(readFileSync(url, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const require = createRequire(url);
  new Function("require", "module", "exports", source)(
    (name) =>
      name.startsWith(".") ? load(new URL(`${name}.ts`, url)) : require(name),
    module,
    module.exports,
  );
  return module.exports;
}
const { workspaceCommand } = load(
  new URL("../lib/server/workspace-commands.ts", import.meta.url),
);

test("confirmation forwards the unchanged atomic profile/skills body and original operation key", async () => {
  const payload = {
    profile: {
      expected_version: 4,
      headline: "Electrical engineering",
      region: "Seattle",
      cap: 3,
    },
    skills: [{ name: "Circuit design", level: 2 }],
    skills_confirmed: true,
  };
  const api = {
    request: async (path, options) => {
      assert.equal(path, "/v1/candidates/me/onboarding");
      assert.equal(options.method, "POST");
      assert.equal(options.key, "confirmation-12345678");
      assert.deepEqual(options.body, payload);
      return {
        data: { candidate: { version: 5 }, skills: payload.skills, version: 5 },
      };
    },
  };
  const response = await workspaceCommand(
    api,
    "candidate.onboarding.confirm",
    payload,
    "confirmation-12345678",
  );
  assert.equal(response.version, 5);
});

test("confirmation propagates server rejection without success or a second profile/skills mutation", async () => {
  let calls = 0;
  const api = {
    request: async () => {
      calls += 1;
      throw new Error("The reviewed version is stale");
    },
  };
  await assert.rejects(
    workspaceCommand(
      api,
      "candidate.onboarding.confirm",
      { profile: {}, skills: [], skills_confirmed: true },
      "confirmation-12345678",
    ),
    /reviewed version is stale/,
  );
  assert.equal(calls, 1);
});
