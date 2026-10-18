import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const url = new URL("../lib/server/navigation-bridge.ts", import.meta.url);
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
const { createNavigationBridge } = module.exports;
const env = {
  NODE_ENV: "production",
  CAREER_KITCHEN_API_URL: "https://api.example.test",
};
const origin = "https://career.example.test";
const body = JSON.stringify({
  message: "Tell me about suitable fields",
  consent_to_gemini: true,
  history: [],
  draft: {},
  target: "https://foreign.example.test",
});
function request(headers = {}, value = body) {
  return new Request(
    `${origin}/api/navigation/onboarding?target=https://foreign.example.test`,
    {
      method: "POST",
      headers: {
        Origin: origin,
        "Content-Type": "application/json",
        "Idempotency-Key": "onboarding-12345678",
        ...headers,
      },
      body: value,
    },
  );
}

test("onboarding uses fixed upstream path, cookie auth and exact retry body/key", async () => {
  const bridge = createNavigationBridge(
    env,
    async (url, options) => {
      assert.equal(
        String(url),
        "https://api.example.test/v1/navigation/onboarding",
      );
      assert.equal(
        options.headers.Authorization,
        "Bearer private-session-token",
      );
      assert.equal(options.headers["Idempotency-Key"], "onboarding-12345678");
      assert.equal(options.body.toString(), body);
      assert.equal(options.cache, "no-store");
      assert.equal(options.redirect, "error");
      return Response.json({ data: { reply: "Question" } });
    },
    async () => "private-session-token",
    "v1/navigation/onboarding",
  );
  const response = await bridge.POST(request());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.doesNotMatch(await response.text(), /private-session-token/);
});

test("onboarding retains origin, authentication, JSON and request-size guards", async () => {
  const bridge = createNavigationBridge(
    env,
    async () => assert.fail("must not contact upstream"),
    async () => "private-session-token",
    "v1/navigation/onboarding",
  );
  assert.equal(
    (await bridge.POST(request({ Origin: "https://foreign.example.test" })))
      .status,
    403,
  );
  assert.equal(
    (await bridge.POST(request({ "Content-Type": "text/plain" }))).status,
    415,
  );
  assert.equal(
    (await bridge.POST(request({}, "x".repeat(100001)))).status,
    413,
  );
  assert.equal((await bridge.POST(request({}, "{invalid"))).status, 422);
  const anonymous = createNavigationBridge(
    env,
    async () => assert.fail("must not contact upstream"),
    async () => {
      throw Object.assign(new Error("private auth detail"), { status: 401 });
    },
    "v1/navigation/onboarding",
  );
  const response = await anonymous.POST(request());
  assert.equal(response.status, 401);
  assert.doesNotMatch(await response.text(), /private auth detail/);
});

test("upstream provider errors remain safe and are not converted to success", async () => {
  const bridge = createNavigationBridge(
    env,
    async () =>
      Response.json(
        {
          error: {
            code: "CHAT_UNAVAILABLE",
            message: "private provider diagnostic",
          },
        },
        { status: 503 },
      ),
    async () => "session-token",
    "v1/navigation/onboarding",
  );
  const response = await bridge.POST(request());
  assert.equal(response.status, 503);
  assert.doesNotMatch(await response.text(), /private provider diagnostic/);
});
