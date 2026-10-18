import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const root = fileURLToPath(new URL("../", import.meta.url));
const SITE = "https://career.example";
const SUPABASE = "https://project.supabase.co";
const AUTH_URL = `${SUPABASE}/auth/v1/authorize?provider=linkedin_oidc&code_challenge=challenge&code_challenge_method=s256`;

function fixture({
  enabled = true,
  exchangeError = null,
  authorizationUrl = AUTH_URL,
  availabilityError = false,
  confirmedEmail = true,
} = {}) {
  const modules = new Map();
  const cookieValues = new Map();
  const writtenCookies = [];
  const oauthCalls = [];
  const signupCalls = [];
  const exchangeCalls = [];
  const signOutCalls = [];
  const fetchCalls = [];
  const store = {
    get: (name) =>
      cookieValues.has(name)
        ? { name, value: cookieValues.get(name) }
        : undefined,
    getAll: () => [...cookieValues].map(([name, value]) => ({ name, value })),
    set: (name, value, options) => {
      cookieValues.set(name, value);
      writtenCookies.push({ name, value, options });
    },
    delete: (name) => cookieValues.delete(name),
  };
  const supabase = {
    auth: {
      signInWithOAuth: async (input) => {
        oauthCalls.push(input);
        return { data: { url: authorizationUrl }, error: null };
      },
      signUp: async (input) => {
        signupCalls.push(input);
        return { data: { session: null }, error: null };
      },
      exchangeCodeForSession: async (code) => {
        exchangeCalls.push(code);
        return {
          data: {
            user: confirmedEmail
              ? {
                  email: "person@example.test",
                  email_confirmed_at: "2026-10-18T00:00:00Z",
                }
              : { email: undefined },
            session: exchangeError
              ? null
              : { access_token: "private-test-token" },
          },
          error: exchangeError,
        };
      },
      signOut: async (input) => {
        signOutCalls.push(input);
        return { error: null };
      },
    },
  };
  const session = {
    authMode: () => "supabase",
    supabaseServer: async () => supabase,
  };
  const fetch = async (url, options) => {
    fetchCalls.push({ url: String(url), options });
    if (availabilityError) throw new Error("private upstream details");
    return Response.json({
      external: { linkedin_oidc: enabled, linkedin: true },
    });
  };
  function load(relative) {
    const filename = resolvePath(root, relative);
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
    const require = createRequire(pathToFileURL(filename));
    const resolve = (name) => {
      if (name === "next/headers") return { cookies: async () => store };
      if (name === "@/lib/server/session") return session;
      if (name.startsWith("@/")) return load(`${name.slice(2)}.ts`);
      if (name.startsWith("."))
        return load(`${resolvePath(dirname(filename), name)}.ts`);
      return require(name);
    };
    new Function("exports", "require", "module", "fetch", source)(
      module.exports,
      resolve,
      module,
      fetch,
    );
    return module.exports;
  }
  return {
    load,
    store,
    writtenCookies,
    oauthCalls,
    signupCalls,
    exchangeCalls,
    signOutCalls,
    fetchCalls,
  };
}

function withEnvironment(run) {
  return async () => {
    const values = {
      NODE_ENV: "production",
      CAREER_KITCHEN_SITE_URL: SITE,
      SUPABASE_URL: SUPABASE,
      SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test_not_a_secret",
    };
    const previous = Object.fromEntries(
      Object.keys(values).map((name) => [name, process.env[name]]),
    );
    Object.assign(process.env, values);
    try {
      await run();
    } finally {
      for (const [name, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[name];
        else process.env[name] = value;
      }
    }
  };
}

function oauthRequest(body, origin = SITE) {
  return new Request(`${SITE}/api/auth/oauth`, {
    method: "POST",
    headers: { origin, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

test(
  "LinkedIn starts the OIDC provider with an HttpOnly, bounded navigation intent",
  withEnvironment(async () => {
    const f = fixture();
    const { POST } = f.load("app/api/auth/oauth/route.ts");
    const response = await POST(
      oauthRequest({
        role: "employer",
        mode: "get-started",
        next: "https://attacker.example",
      }),
    );
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(await response.json(), { redirectTo: AUTH_URL });
    assert.deepEqual(f.oauthCalls, [
      {
        provider: "linkedin_oidc",
        options: {
          scopes: "openid profile email",
          redirectTo: `${SITE}/auth/callback`,
          skipBrowserRedirect: true,
        },
      },
    ]);
    assert.equal(f.fetchCalls[0].url, `${SUPABASE}/auth/v1/settings`);
    assert.deepEqual(f.writtenCookies, [
      {
        name: "ck-auth-intent",
        value: JSON.stringify({ role: "employer", mode: "get-started" }),
        options: {
          httpOnly: true,
          secure: true,
          sameSite: "lax",
          path: "/",
          maxAge: 3600,
        },
      },
    ]);
  }),
);

test(
  "OAuth rejects cross-origin starts before it contacts the provider",
  withEnvironment(async () => {
    const f = fixture();
    const { POST } = f.load("app/api/auth/oauth/route.ts");
    const response = await POST(
      oauthRequest({ role: "candidate" }, "https://attacker.example"),
    );
    assert.equal(response.status, 403);
    assert.equal(f.fetchCalls.length, 0);
    assert.equal(f.oauthCalls.length, 0);
  }),
);

test(
  "legacy LinkedIn alone is not presented as OIDC availability",
  withEnvironment(async () => {
    const f = fixture({ enabled: false });
    const config = await f
      .load("app/api/auth/config/route.ts")
      .GET(new Request(`${SITE}/api/auth/config`));
    assert.equal((await config.json()).linkedin, "disabled");
    const response = await f
      .load("app/api/auth/oauth/route.ts")
      .POST(oauthRequest({}));
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error.code, "LINKEDIN_UNAVAILABLE");
    assert.equal(f.oauthCalls.length, 0);
  }),
);

test(
  "OAuth never forwards an unexpected authorization URL",
  withEnvironment(async () => {
    const f = fixture({ authorizationUrl: "https://attacker.example/sign-in" });
    const response = await f
      .load("app/api/auth/oauth/route.ts")
      .POST(oauthRequest({}));
    assert.equal(response.status, 503);
    assert.equal(f.writtenCookies.length, 0);
    assert.doesNotMatch(JSON.stringify(await response.json()), /attacker/);
  }),
);

test(
  "provider discovery outages leave email available and report no enabled LinkedIn provider",
  withEnvironment(async () => {
    const f = fixture({ availabilityError: true });
    const response = await f
      .load("app/api/auth/config/route.ts")
      .GET(new Request(`${SITE}/api/auth/config`));
    assert.deepEqual(await response.json(), {
      mode: "supabase",
      linkedin: "unavailable",
    });
    assert.equal(f.oauthCalls.length, 0);
  }),
);

test(
  "email confirmation keeps the chosen workspace and canonical callback origin",
  withEnvironment(async () => {
    const f = fixture();
    const request = new Request(`${SITE}/api/auth/session`, {
      method: "POST",
      headers: { origin: SITE, "content-type": "application/json" },
      body: JSON.stringify({
        email: "person@example.test",
        password: "test-password-only",
        role: "employer",
        mode: "get-started",
      }),
    });
    const response = await f
      .load("app/api/auth/session/route.ts")
      .POST(request);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      needsEmailConfirmation: true,
      redirectTo: "/onboarding/employer",
    });
    assert.equal(
      f.signupCalls[0].options.emailRedirectTo,
      `${SITE}/auth/callback`,
    );
    assert.equal(
      f.store.get("ck-auth-intent").value,
      JSON.stringify({ role: "employer", mode: "get-started" }),
    );
  }),
);

test(
  "callback exchanges PKCE code and sends each workspace to its own onboarding",
  withEnvironment(async () => {
    for (const role of ["candidate", "employer"]) {
      const f = fixture();
      f.store.set(
        "ck-auth-intent",
        JSON.stringify({ role, mode: "get-started" }),
      );
      const response = await f
        .load("app/auth/callback/route.ts")
        .GET(
          new Request(
            `${SITE}/auth/callback?code=one-time-code&next=https://attacker.example`,
          ),
        );
      assert.equal(response.status, 303);
      assert.equal(response.headers.get("cache-control"), "no-store");
      assert.equal(
        response.headers.get("location"),
        `${SITE}/onboarding/${role}`,
      );
      assert.deepEqual(f.exchangeCalls, ["one-time-code"]);
      assert.equal(f.store.get("ck-auth-intent"), undefined);
    }
  }),
);

test(
  "callback does not turn a role preference into an arbitrary path or authority",
  withEnvironment(async () => {
    const f = fixture();
    f.store.set(
      "ck-auth-intent",
      JSON.stringify({
        role: "//attacker.example",
        mode: "operator",
        next: "/operations",
      }),
    );
    const response = await f
      .load("app/auth/callback/route.ts")
      .GET(
        new Request(
          `${SITE}/auth/callback?code=one-time-code&role=operator&next=//attacker.example`,
        ),
      );
    assert.equal(response.headers.get("location"), `${SITE}/candidate`);
  }),
);

test(
  "cancelled OAuth is sanitized and never exchanges a code",
  withEnvironment(async () => {
    const f = fixture();
    const response = await f
      .load("app/auth/callback/route.ts")
      .GET(
        new Request(
          `${SITE}/auth/callback?error=access_denied&error_description=private-provider-details&code=untrusted`,
        ),
      );
    assert.equal(
      response.headers.get("location"),
      `${SITE}/sign-in?role=candidate&auth_error=cancelled`,
    );
    assert.equal(f.exchangeCalls.length, 0);
    assert.doesNotMatch(await response.text(), /private-provider-details/);
  }),
);

test(
  "expired or cross-browser callback returns an actionable sign-in failure",
  withEnvironment(async () => {
    const f = fixture({
      exchangeError: new Error("private PKCE verifier details"),
    });
    const response = await f
      .load("app/auth/callback/route.ts")
      .GET(new Request(`${SITE}/auth/callback?code=expired`));
    assert.equal(
      response.headers.get("location"),
      `${SITE}/sign-in?role=candidate&auth_error=expired`,
    );
    assert.doesNotMatch(await response.text(), /private PKCE/);
  }),
);

test(
  "the maintained SSR client actually persists a PKCE challenge in HttpOnly cookies",
  withEnvironment(async () => {
    const f = fixture();
    const { supabaseServer } = f.load("lib/server/session.ts");
    const client = await supabaseServer();
    const { data, error } = await client.auth.signInWithOAuth({
      provider: "linkedin_oidc",
      options: {
        redirectTo: `${SITE}/auth/callback`,
        skipBrowserRedirect: true,
      },
    });
    assert.equal(error, null);
    const target = new URL(data.url);
    assert.equal(target.searchParams.get("provider"), "linkedin_oidc");
    assert.equal(target.searchParams.get("code_challenge_method"), "s256");
    assert.ok(target.searchParams.get("code_challenge").length >= 43);
    assert.ok(
      f.writtenCookies.some(
        ({ name, options }) =>
          name.includes("code-verifier") &&
          options.httpOnly &&
          options.secure &&
          options.sameSite === "lax",
      ),
    );
    assert.equal(f.fetchCalls.length, 0);
  }),
);

test(
  "OAuth without a confirmed email returns to email sign-in before entering the workspace",
  withEnvironment(async () => {
    const f = fixture({ confirmedEmail: false });
    const response = await f
      .load("app/auth/callback/route.ts")
      .GET(new Request(`${SITE}/auth/callback?code=one-time-code`));
    assert.equal(
      response.headers.get("location"),
      `${SITE}/sign-in?role=candidate&auth_error=email_required`,
    );
    assert.deepEqual(f.signOutCalls, [{ scope: "local" }]);
    assert.doesNotMatch(await response.text(), /private-test-token/);
  }),
);
