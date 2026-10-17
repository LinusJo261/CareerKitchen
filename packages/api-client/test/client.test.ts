import assert from "node:assert/strict";
import test from "node:test";
import { apiError, createCareerKitchenClient } from "../src/index.js";

test("request-scoped transport adds auth, disables caches, and exposes typed identity", async () => {
  let captured: Request | undefined;
  const client = createCareerKitchenClient({
    baseUrl: "https://api.example.invalid",
    accessToken: async () => "fictional-token",
    fetch: async (input) => {
      captured = input as Request;
      return Response.json({ data: { id: "fictional-id", email: "fictional@example.invalid", platform_roles: [], memberships: [] } });
    },
  });
  const result = await client.GET("/v1/sessions/me");
  assert.equal(result.data?.data.email, "fictional@example.invalid");
  assert.equal(captured?.headers.get("Authorization"), "Bearer fictional-token");
  assert.equal(captured?.cache, "no-store");
  assert.equal(captured?.redirect, "error");
});

test("a stale mutation is sent once with the caller's stable operation key", async () => {
  let attempts = 0;
  const client = createCareerKitchenClient({
    baseUrl: "https://api.example.invalid", accessToken: () => "fictional-token",
    fetch: async (input) => {
      attempts++;
      assert.equal((input as Request).headers.get("Idempotency-Key"), "operation-1234");
      return Response.json({ error: { code: "VERSION_CONFLICT", message: "Refresh the resource", request_id: "request-1" } }, { status: 412 });
    },
  });
  const result = await client.POST("/v1/candidates/me/pause", {
    params: { header: { "Idempotency-Key": "operation-1234" } }, body: { expected_version: 1 },
  });
  assert.equal(attempts, 1);
  const error = apiError(result.response, result.error);
  assert.equal(error.status, 412);
  assert.equal(error.code, "VERSION_CONFLICT");
  assert.equal(error.requestId, "request-1");
});

test("an overridden remote base URL cannot exfiltrate a bearer token", async () => {
  let tokenReads = 0;
  const client = createCareerKitchenClient({ baseUrl: "https://api.example.invalid", accessToken: () => { tokenReads++; return "private-token"; } });
  await assert.rejects(client.GET("/v1/sessions/me", { baseUrl: "https://attacker.invalid" }), /another API origin/);
  assert.equal(tokenReads, 0);
});

test("HTTP is allowed only on loopback and configured URL credentials are rejected", () => {
  assert.throws(() => createCareerKitchenClient({ baseUrl: "http://public.invalid", accessToken: () => "token" }), /HTTPS/);
  assert.throws(() => createCareerKitchenClient({ baseUrl: "https://user:password@api.invalid", accessToken: () => "token" }), /credentials/);
  assert.ok(createCareerKitchenClient({ baseUrl: "http://127.0.0.1:8000", accessToken: () => "token" }));
});

test("multipart helper sends actual binary bytes and a stable operation key", async () => {
  const client = createCareerKitchenClient({
    baseUrl: "https://api.example.invalid", accessToken: () => "fictional-token",
    fetch: async (input) => {
      const request = input as Request;
      assert.match(request.headers.get("Content-Type") ?? "", /multipart\/form-data; boundary=/);
      assert.equal(request.headers.get("Idempotency-Key"), "resume-operation-1");
      const body = await request.formData();
      const uploaded = body.get("file");
      assert.ok(uploaded instanceof Blob);
      assert.equal(await uploaded.text(), "Fictional resume");
      return Response.json({ data: { object_id: "fictional-id", size: 16, sha256: "test-hash", parse_status: "DRAFT_REQUIRES_CONFIRMATION", suggested_summary: "Fictional resume", candidate_version: 2 } });
    },
  });
  const result = await client.uploadMultipart("/v1/candidates/me/resume", {
    params: { header: { "Idempotency-Key": "resume-operation-1" } },
    body: { file: new Blob(["Fictional resume"], { type: "text/plain" }) },
  });
  assert.equal(result.data.parse_status, "DRAFT_REQUIRES_CONFIRMATION");
});

