// Exercise actual gateway modules with only Next's per-request cookie store mocked.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";

const modules = new Map();
const cookieValues = new Map();
const cookieOptions = new Map();
const cookieStore = {
  get: (name) =>
    cookieValues.has(name) ? { value: cookieValues.get(name) } : undefined,
  set: (name, value, options) => {
    cookieValues.set(name, value);
    cookieOptions.set(name, options);
  },
  delete: (name) => cookieValues.delete(name),
};
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
  const resolve = (name) => {
    if (name === "next/headers") return { cookies: async () => cookieStore };
    if (name === "@supabase/ssr")
      return {
        createServerClient: () =>
          assert.fail("Sample mode must not contact Supabase"),
      };
    if (name.startsWith("@/"))
      return load(new URL(`../${name.slice(2)}.ts`, import.meta.url));
    return name.startsWith(".")
      ? load(new URL(`${name}.ts`, url))
      : require(name);
  };
  new Function(
    "exports",
    "require",
    "module",
    "__filename",
    "__dirname",
    source,
  )(module.exports, resolve, module, filename, dirname(filename));
  return module.exports;
}
const session = load(new URL("../lib/server/session.ts", import.meta.url));
const { Backend, backendFor } = load(
  new URL("../lib/server/backend.ts", import.meta.url),
);
const login = load(
  new URL("../app/api/auth/session/route.ts", import.meta.url),
).POST;
const logout = load(
  new URL("../app/api/auth/logout/route.ts", import.meta.url),
).POST;
const config = load(
  new URL("../app/api/auth/config/route.ts", import.meta.url),
).GET;
const navigation = load(
  new URL("../app/api/navigation/chat/route.ts", import.meta.url),
);
const ORIGIN = "http://127.0.0.1:3000";
const request = (input = {}, headers = {}, origin = ORIGIN) =>
  new Request(`${origin}/api/auth/session`, {
    method: "POST",
    headers: { origin, "content-type": "application/json", ...headers },
    body: JSON.stringify(input),
  });
const enabled = {
  FRONTEND_SAMPLE_DEMO: "",
  SAMPLE_SESSION_SECRET: "",
  SAMPLE_SUPABASE_URL: "",
  SAMPLE_SUPABASE_PUBLISHABLE_KEY: "",
  SAMPLE_CANDIDATE_PASSWORD: "",
  SAMPLE_EMPLOYER_PASSWORD: "",
  NODE_ENV: "development",
  FRONTEND_LOCAL_DEMO: "true",
  AUTH_MODE: "local",
  ALLOW_DEV_AUTH: "true",
  DEV_JWT_SECRET: "sample-test-signing-key-at-least-32-characters",
  CAREER_KITCHEN_API_URL: "http://127.0.0.1:8000",
  CAREER_KITCHEN_SAMPLE_API_URL: "http://127.0.0.1:8001",
  CAREER_KITCHEN_SITE_URL: "",
  SUPABASE_URL: "",
  NEXT_PUBLIC_SUPABASE_URL: "",
  SUPABASE_PUBLISHABLE_KEY: "",
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "",
};
async function fixture(run) {
  const previous = Object.fromEntries(
    Object.keys(enabled).map((key) => [key, process.env[key]]),
  );
  const fetcher = globalThis.fetch;
  cookieValues.clear();
  cookieOptions.clear();
  Object.assign(process.env, enabled);
  try {
    await run();
  } finally {
    globalThis.fetch = fetcher;
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    cookieValues.clear();
    cookieOptions.clear();
  }
}
const errorCode = (code) => (error) => error.code === code;

test("sample sign-in checks the dedicated market before issuing an HttpOnly, signed session", async () =>
  fixture(async () => {
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      return Response.json({
        data: String(url).endsWith("/v1/demo/status")
          ? { ready: true }
          : { id: "sample-user" },
      });
    };
    cookieValues.set("ck-local-session", "previous-local-token");
    const response = await login(
      request({ mode: "sample", account: "candidate-000001" }),
    );
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      redirectTo: "/candidate",
      mode: "sample",
    });
    assert.deepEqual(
      calls.map((call) => call.url),
      [
        "http://127.0.0.1:8001/v1/demo/status",
        "http://127.0.0.1:8001/v1/sessions/me",
      ],
    );
    assert.equal(cookieValues.has("ck-local-session"), false);
    assert.deepEqual(cookieOptions.get("ck-sample-session"), {
      httpOnly: true,
      sameSite: "strict",
      secure: false,
      path: "/",
      maxAge: 1800,
    });
    const connection = await session.sessionConnection(request());
    assert.equal(connection.mode, "sample");
    const claims = JSON.parse(
      Buffer.from(connection.token.split(".")[1], "base64url").toString(),
    );
    assert.equal(claims.sub, session.sampleIdentity("candidate-000001"));
    // UUIDv5 fixtures computed independently by scripts.seed_samples.identity.
    assert.equal(claims.sub, "b522d2c0-2b19-5ba3-a017-4b7a76cba9bb");
    assert.equal(
      session.sampleIdentity("employer"),
      "cd724916-b2c7-5738-bc4d-a6497a3b4d2f",
    );
    assert.equal(claims.role, undefined);
    assert.notEqual(claims.sub, session.fictionalIdentity("candidate-01"));
    assert.equal(await session.currentSessionMode(request()), "sample");
    const backend = await backendFor(
      request({}, { "x-career-kitchen-mode": "standard" }),
    );
    assert.equal(backend.mode, "sample");
    await backend.get("/v1/candidates/me");
    assert.equal(calls.at(-1).url, "http://127.0.0.1:8001/v1/candidates/me");
  }));

test("unready or wrong APIs never bootstrap a user or set a sample cookie", async () =>
  fixture(async () => {
    for (const status of [false, "true", null]) {
      const calls = [];
      globalThis.fetch = async (url) => {
        calls.push(url);
        return Response.json({ data: { ready: status } });
      };
      const response = await login(
        request({ mode: "sample", account: "employer" }),
      );
      assert.equal(response.status, 503);
      assert.equal((await response.json()).error.code, "DEMO_NOT_READY");
      assert.deepEqual(calls, ["http://127.0.0.1:8001/v1/demo/status"]);
      assert.equal(cookieValues.has("ck-sample-session"), false);
    }
  }));

test("sample mode is opt-in, loopback only, and disabled in production", async () =>
  fixture(async () => {
    globalThis.fetch = () =>
      assert.fail("Disabled demo must not contact an API");
    assert.equal((await (await config(request())).json()).sampleDemo, true);
    for (const [key, value] of [
      ["FRONTEND_LOCAL_DEMO", "false"],
      ["ALLOW_DEV_AUTH", "false"],
      ["NODE_ENV", "production"],
    ]) {
      process.env[key] = value;
      assert.equal((await login(request({ mode: "sample" }))).status, 403);
      assert.equal((await (await config(request())).json()).sampleDemo, false);
      process.env[key] = enabled[key];
    }
    assert.equal(
      (await login(request({ mode: "sample" }, {}, "https://career.example")))
        .status,
      403,
    );
    const forgedHost = request(
      { mode: "sample" },
      { host: "localhost:3000", origin: "https://localhost:3000" },
      "https://career.example",
    );
    assert.equal((await login(forgedHost)).status, 403);
  }));

test("demo entry keeps same-origin mutation checks and rejects arbitrary accounts", async () =>
  fixture(async () => {
    globalThis.fetch = () =>
      assert.fail("Rejected entry must not contact an API");
    for (const headers of [
      { origin: "https://attacker.example" },
      { "sec-fetch-site": "cross-site" },
    ])
      assert.equal(
        (await login(request({ mode: "sample" }, headers))).status,
        403,
      );
    for (const account of [
      "operations",
      "candidate-000000",
      "candidate-100001",
      "candidate-099999",
      "candidate-01",
      "../employer",
    ])
      assert.equal(
        (await login(request({ mode: "sample", account }))).status,
        422,
      );
  }));

test("sample destination rejects remote addresses, credentials and the normal API port", async () =>
  fixture(async () => {
    for (const value of [
      "https://remote.example",
      "http://127.0.0.1:8000",
      "http://localhost:8000",
      "http://user:password@127.0.0.1:8001",
      "http://127.0.0.1:8001/path",
      "http://127.0.0.1:8001?secret=bad",
      "http://localhost.attacker.example:8001",
    ]) {
      process.env.CAREER_KITCHEN_SAMPLE_API_URL = value;
      assert.throws(
        () => session.sampleApiBase(),
        errorCode("DEMO_NOT_CONFIGURED"),
      );
    }
  }));

test("forged, expired and destination-changed sample cookies never fall back to a normal session", async () =>
  fixture(async () => {
    cookieValues.set("ck-local-session", "normal-token-must-not-be-used");
    await session.setSampleSession("sample-token");
    const signed = cookieValues.get("ck-sample-session");
    for (const forged of [
      signed.slice(0, -1) + "!",
      signed.replace(/.$/, "é"),
      "sample-token",
      `${signed}.extra`,
    ]) {
      cookieValues.set("ck-sample-session", forged);
      await assert.rejects(
        session.sessionConnection(request()),
        errorCode("INVALID_DEMO_SESSION"),
      );
    }
    cookieValues.set("ck-sample-session", signed);
    process.env.CAREER_KITCHEN_SAMPLE_API_URL = "http://127.0.0.1:8002";
    await assert.rejects(
      session.sessionConnection(request()),
      errorCode("INVALID_DEMO_SESSION"),
    );
    process.env.CAREER_KITCHEN_SAMPLE_API_URL =
      enabled.CAREER_KITCHEN_SAMPLE_API_URL;
    const now = Date.now;
    try {
      Date.now = () => now() - 3600_000;
      await session.setSampleSession("expired-token");
    } finally {
      Date.now = now;
    }
    await assert.rejects(
      session.sessionConnection(request()),
      errorCode("INVALID_DEMO_SESSION"),
    );
  }));

test("sample mode cannot be selected by request headers and local fixtures retain their API", async () =>
  fixture(async () => {
    await session.setFictionalSession(session.fictionalToken("candidate-01"));
    const calls = [];
    globalThis.fetch = async (url) => {
      calls.push(url);
      return Response.json({ data: {} });
    };
    const backend = await backendFor(
      request(
        {},
        {
          "x-demo-mode": "sample",
          "x-career-kitchen-api-url": "http://127.0.0.1:8001",
        },
      ),
    );
    assert.equal(backend.mode, "standard");
    await backend.get("/v1/sessions/me");
    assert.deepEqual(calls, ["http://127.0.0.1:8000/v1/sessions/me"]);
    await session.setSampleSession("sample-token");
    await session.setFictionalSession("new-local-token");
    assert.equal(cookieValues.has("ck-sample-session"), false);
    assert.equal(await session.currentSessionMode(request()), "local");
  }));

test("sample chat uses the sample destination and ignores caller-selected bearer credentials", async () =>
  fixture(async () => {
    await session.setSampleSession("sample-workspace-token");
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push({ url: String(url), options });
      return Response.json({ data: {} });
    };
    const chatRequest = new Request(`${ORIGIN}/api/navigation/chat`, {
      method: "POST",
      headers: {
        origin: ORIGIN,
        "content-type": "application/json",
        "idempotency-key": "demo-message-12345",
        authorization: "Bearer caller-selected-token",
      },
      body: JSON.stringify({ message: "Explain this sample market" }),
    });
    assert.equal((await navigation.POST(chatRequest)).status, 200);
    assert.equal(calls[0].url, "http://127.0.0.1:8001/v1/navigation/chat");
    assert.equal(
      calls[0].options.headers.Authorization,
      "Bearer sample-workspace-token",
    );
  }));

test("logout clears sample mode even when its dedicated API is offline", async () =>
  fixture(async () => {
    await session.setSampleSession("sample-workspace-token");
    globalThis.fetch = async () => {
      throw new Error("offline");
    };
    assert.equal((await logout(request())).status, 200);
    assert.equal(cookieValues.has("ck-sample-session"), false);
    assert.equal(cookieValues.has("ck-local-session"), false);
  }));

function hosted() {
  Object.assign(process.env, {
    NODE_ENV: "production", FRONTEND_SAMPLE_DEMO: "true", FRONTEND_LOCAL_DEMO: "false",
    AUTH_MODE: "supabase", ALLOW_DEV_AUTH: "false", DEV_JWT_SECRET: "",
    SAMPLE_SESSION_SECRET: "independent-sample-session-secret-32-characters",
    CAREER_KITCHEN_API_URL: "https://api.career.example",
    CAREER_KITCHEN_SAMPLE_API_URL: "https://sample.career.example",
    SAMPLE_SUPABASE_URL: "https://sample.supabase.co",
    SAMPLE_SUPABASE_PUBLISHABLE_KEY: "publishable-test-key",
    SAMPLE_CANDIDATE_PASSWORD: "candidate-private-password-at-least-32",
    SAMPLE_EMPLOYER_PASSWORD: "employer-private-password-at-least-32",
  });
}

test("hosted sample uses Supabase, separate HTTPS destination and Secure HttpOnly cookies", async () => fixture(async () => {
  hosted();
  const token = Buffer.from(JSON.stringify({alg:"ES256"})).toString("base64url") + ".test.signature";
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({url:String(url),options});
    return String(url).includes("/auth/v1/token") ? Response.json({access_token:token}) : Response.json({data:{ready:true}});
  };
  assert.equal(session.sampleDemoAvailable(new Request("https://career.example")),true);
  const response = await login(request({mode:"sample",account:"employer"},{},"https://career.example"));
  assert.equal(response.status,200);
  assert.equal(calls[0].url,"https://sample.supabase.co/auth/v1/token?grant_type=password");
  assert.deepEqual(JSON.parse(calls[0].options.body), {email:"employer@samples.example.invalid",password:process.env.SAMPLE_EMPLOYER_PASSWORD});
  assert.ok(calls.slice(1).every(c => c.url.startsWith("https://sample.career.example/")));
  assert.equal(cookieOptions.get("ck-sample-session").secure,true);
  assert.equal(cookieOptions.get("ck-sample-session").httpOnly,true);
  assert.equal((await session.sessionConnection(new Request("https://career.example"))).token,token);
  assert.equal(JSON.stringify(await response.json()).includes(token),false);
}));

test("hosted sample rejects development tokens, missing credentials and a normal API destination", async () => fixture(async () => {
  hosted();
  globalThis.fetch = async () => Response.json({access_token:Buffer.from(JSON.stringify({alg:"HS256"})).toString("base64url")+".test.signature"});
  await assert.rejects(() => session.sampleToken("employer"),errorCode("DEMO_AUTH_UNAVAILABLE"));
  assert.equal(cookieValues.size,0);
  process.env.CAREER_KITCHEN_SAMPLE_API_URL = process.env.CAREER_KITCHEN_API_URL;
  assert.throws(() => session.sampleApiBase(),errorCode("DEMO_NOT_CONFIGURED"));
  process.env.CAREER_KITCHEN_SAMPLE_API_URL = "http://sample.career.example";
  assert.throws(() => session.sampleApiBase(),errorCode("DEMO_NOT_CONFIGURED"));
  process.env.SAMPLE_EMPLOYER_PASSWORD = "";
  assert.equal(session.sampleDemoAvailable(new Request("https://career.example")),false);
}));
