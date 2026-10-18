import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";

function sessionModule(auth, options = {}) {
  const modules = new Map();
  function load(url) {
    const filename = fileURLToPath(url);
    if (modules.has(filename)) return modules.get(filename).exports;
    const module = { exports: {} };
    modules.set(filename, module);
    const require = createRequire(url);
    const source = ts.transpileModule(readFileSync(filename, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: filename,
    }).outputText;
    const resolve = (name) => {
      if (name === "next/headers")
        return { cookies: async () => ({ get: () => undefined, getAll: () => [], set: () => {} }) };
      if (name === "@supabase/ssr")
        return {
          createServerClient: (...args) => {
            options.client?.(...args);
            return { auth };
          },
        };
      return name.startsWith(".")
        ? load(new URL(`${name}.ts`, url))
        : require(name);
    };
    new Function("exports", "require", "module", source)(
      module.exports,
      resolve,
      module,
    );
    return module.exports;
  }
  return load(new URL("../lib/server/session.ts", import.meta.url));
}

const request = () => new Request("https://career.example/api/workspace");
async function withSupabase(run) {
  const values = {
    NODE_ENV: "production",
    SUPABASE_URL: "https://project.supabase.co",
    SUPABASE_PUBLISHABLE_KEY: "test-publishable-key",
  };
  const previous = Object.fromEntries(
    Object.keys(values).map((key) => [key, process.env[key]]),
  );
  try {
    Object.assign(process.env, values);
    await run();
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

test("server forwards access token only after provider verifies user and keeps cookies HTTP-only", async () => {
  await withSupabase(async () => {
    const calls = [];
    const { accessToken } = sessionModule(
      {
        async getUser() {
          calls.push("verify");
          return { data: { user: { id: "verified-user" } }, error: null };
        },
        async getSession() {
          calls.push("session");
          return {
            data: { session: { access_token: "verified-session-token" } },
            error: null,
          };
        },
      },
      {
        client: (url, key, options) => {
          assert.equal(url, process.env.SUPABASE_URL);
          assert.equal(key, process.env.SUPABASE_PUBLISHABLE_KEY);
          assert.equal(options.cookieOptions.httpOnly, true);
          assert.equal(options.cookieOptions.secure, true);
          assert.equal(options.cookieOptions.sameSite, "lax");
        },
      },
    );
    assert.equal(await accessToken(request()), "verified-session-token");
    assert.deepEqual(calls, ["verify", "session"]);
  });
});

test("provider outages stay retryable and do not become misleading expired-session errors", async () => {
  await withSupabase(async () => {
    for (const status of [0, 429, 500, 503, undefined]) {
      const { accessToken } = sessionModule({
        async getUser() {
          return { data: { user: null }, error: { status } };
        },
        async getSession() {
          assert.fail("Unverified cookies must never be forwarded");
        },
      });
      await assert.rejects(
        accessToken(request()),
        (error) => error.status === 503 && error.code === "AUTH_UNAVAILABLE",
      );
    }
  });
});

test("revoked or missing Supabase sessions require sign-in and never forward cookie tokens", async () => {
  await withSupabase(async () => {
    for (const error of [
      null,
      { status: 400 },
      { status: 401 },
      { status: 403 },
    ]) {
      const { accessToken } = sessionModule({
        async getUser() {
          return { data: { user: null }, error };
        },
        async getSession() {
          assert.fail("Unverified cookies must never be forwarded");
        },
      });
      await assert.rejects(
        accessToken(request()),
        (error) => error.status === 401 && error.code === "UNAUTHORIZED",
      );
    }
  });
});

test("refresh failure after user verification is classified without exposing provider error text", async () => {
  await withSupabase(async () => {
    const privateMessage = "private-provider-detail";
    const { accessToken } = sessionModule({
      async getUser() {
        return { data: { user: { id: "verified-user" } }, error: null };
      },
      async getSession() {
        return {
          data: { session: null },
          error: { status: 503, message: privateMessage },
        };
      },
    });
    await assert.rejects(
      accessToken(request()),
      (error) =>
        error.status === 503 &&
        error.code === "AUTH_UNAVAILABLE" &&
        !error.message.includes(privateMessage),
    );
  });
});

// Deliberately unsigned fixtures: provider verification is mocked. The header is
// used only to decide whether refresh is needed, never as proof of identity.
const tokenWithAlgorithm = (alg) =>
  `${Buffer.from(JSON.stringify({ alg })).toString("base64url")}.fictional-payload.fictional-signature`;

test("legacy session is refreshed once and the exact new asymmetric token is reverified before forwarding", async () => {
  await withSupabase(async () => {
    const oldToken = tokenWithAlgorithm("HS256");
    const newToken = tokenWithAlgorithm("ES256");
    const calls = [];
    const { accessToken } = sessionModule({
      async getUser(token) {
        calls.push(["verify", token]);
        return { data: { user: { id: "same-verified-user" } }, error: null };
      },
      async getSession() {
        calls.push(["session"]);
        return { data: { session: { access_token: oldToken } }, error: null };
      },
      async refreshSession() {
        calls.push(["refresh"]);
        return { data: { session: { access_token: newToken } }, error: null };
      },
    });
    assert.equal(await accessToken(request()), newToken);
    assert.deepEqual(calls, [
      ["verify", undefined],
      ["session"],
      ["refresh"],
      ["verify", newToken],
    ]);
  });
});

test("current asymmetric sessions are not needlessly refreshed", async () => {
  await withSupabase(async () => {
    for (const algorithm of ["ES256", "RS256"]) {
      const token = tokenWithAlgorithm(algorithm);
      const { accessToken } = sessionModule({
        async getUser() {
          return { data: { user: { id: "verified-user" } }, error: null };
        },
        async getSession() {
          return { data: { session: { access_token: token } }, error: null };
        },
        async refreshSession() {
          assert.fail("Current asymmetric token needs no migration refresh");
        },
      });
      assert.equal(await accessToken(request()), token);
    }
  });
});

test("legacy refresh failure fails closed and retains retryable versus signed-out status", async () => {
  await withSupabase(async () => {
    for (const status of [401, 503]) {
      let verificationCalls = 0;
      let refreshCalls = 0;
      const { accessToken } = sessionModule({
        async getUser() {
          verificationCalls++;
          return { data: { user: { id: "verified-user" } }, error: null };
        },
        async getSession() {
          return {
            data: { session: { access_token: tokenWithAlgorithm("HS256") } },
            error: null,
          };
        },
        async refreshSession() {
          refreshCalls++;
          return {
            data: { session: null },
            error: { status, message: "private-provider-detail" },
          };
        },
      });
      await assert.rejects(
        accessToken(request()),
        (error) =>
          error.status === status &&
          !error.message.includes("private-provider-detail"),
      );
      assert.equal(verificationCalls, 1);
      assert.equal(refreshCalls, 1);
    }
  });
});

test("refreshed session must verify as the same user and use an asymmetric signing algorithm", async () => {
  await withSupabase(async () => {
    for (const scenario of [
      "provider-rejected",
      "different-user",
      "still-legacy",
      "unsigned",
    ]) {
      let refreshCalls = 0;
      let verificationCalls = 0;
      const refreshedToken = tokenWithAlgorithm(
        scenario === "still-legacy"
          ? "HS256"
          : scenario === "unsigned"
            ? "none"
            : "ES256",
      );
      const { accessToken } = sessionModule({
        async getUser(token) {
          verificationCalls++;
          if (token && scenario === "provider-rejected")
            return { data: { user: null }, error: { status: 401 } };
          return {
            data: {
              user: {
                id:
                  token && scenario === "different-user"
                    ? "other-user"
                    : "verified-user",
              },
            },
            error: null,
          };
        },
        async getSession() {
          return {
            data: { session: { access_token: tokenWithAlgorithm("HS256") } },
            error: null,
          };
        },
        async refreshSession() {
          refreshCalls++;
          return {
            data: { session: { access_token: refreshedToken } },
            error: null,
          };
        },
      });
      const expectedStatus = ["still-legacy", "unsigned"].includes(scenario)
        ? 503
        : 401;
      await assert.rejects(
        accessToken(request()),
        (error) => error.status === expectedStatus,
      );
      assert.equal(refreshCalls, 1);
      assert.equal(verificationCalls, 2);
    }
  });
});
