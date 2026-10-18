# Connected Next.js frontend

The existing Next.js pages connect to FastAPI through server-side route handlers.
`GET /api/workspace` assembles authorized data for the selected workspace;
`POST /api/workspace/commands` translates explicit actions into versioned API
requests. The shared SWR hook refreshes after successful changes, on focus and
periodically; it never presents fixture records as live state.

The [Gemini navigation chat contract](navigation-chat.md) describes the read-only
`POST /v1/navigation/chat` endpoint used by Career Chef, including server
configuration, user consent, authentication, and retry behavior.

The runnable contract is
`docs/openapi.json`; Swagger is available at `/docs`, ReDoc at `/redoc`, and the
generated TypeScript interfaces are in `packages/api-client/src/schema.ts`.

## Configuration and authentication

The Next.js application uses `@supabase/ssr`, the server-configured
`SUPABASE_URL`/`SUPABASE_PUBLISHABLE_KEY`, and a **server-only** `CAREER_KITCHEN_API_URL`
such as `https://api.example.com`. Configure FastAPI `CORS_ORIGINS` with exact
approved Vercel origins and `TRUSTED_HOSTS` with the API hostname. Preview
environments need their own database and Supabase project. Never pass service-role,
database, encryption, audit, or local signing secrets to a browser.

Supabase handles sign-up, login, confirmed email, password recovery, refresh, and
provider logout. The BFF forwards a session access token. FastAPI verifies it and
loads current account status and permissions from PostgreSQL. Client-selected
roles, email domains, and page guards cannot authorize a backend operation. During
logout, call `POST /v1/sessions/logout` and sign out with Supabase so that both
application access and provider refresh credentials are revoked.

Use the project's maintained [Supabase SSR integration](https://supabase.com/docs/guides/auth/server-side)
for secure cookies. Protect cookie-authenticated Next.js server actions against
CSRF. Do not persist access tokens in local storage or create a global client that
captures a user's token.

## TypeScript client

Run these from `packages/api-client`:

```sh
npm ci
npm run generate
npm run typecheck
npm test
npm run build
```

The private package can be referenced as a local workspace/file dependency from
the v0 source when it is supplied. Its generated types and maintained
`openapi-fetch` transport cover every documented method/path, request body,
parameter, response, and error. No frontend dependency or UI is required by the
backend repository. Regenerate with `python scripts/export_openapi.py` at the
repository root followed by `npm run generate` in the client package after API
changes. CI rejects contract or generated-type drift.

Create a client **per incoming BFF request**, after reading the session from the
existing server-side Supabase helper:

```ts
import "server-only";
import { createCareerKitchenClient, apiError } from "@career-kitchen/api-client";

// session is read from this request's secure Supabase SSR cookie context.
const client = createCareerKitchenClient({
  baseUrl: process.env.CAREER_KITCHEN_API_URL!,
  accessToken: () => session.access_token,
});

const { data, error, response } = await client.GET("/v1/candidates/me");
if (!data) throw apiError(response, error);
const profile = data.data;

// operationKey comes from the pending user action; retain it across exact retries.
const result = await client.POST("/v1/candidates/me/pause", {
  params: { header: { "Idempotency-Key": operationKey } },
  body: { expected_version: profile.version },
});
if (!result.data) throw apiError(result.response, result.error);
```

The client pins the API origin, refuses redirects, disables caching, bounds
request time, and sends exactly one request. It never retries a decision or
changes a version automatically. Refresh state after 409/412; if the user confirms
a new operation with a changed payload, use a new idempotency key. A network retry
of the exact previous operation reuses its original key and payload.

Multipart uploads use a Blob-aware helper; never set a multipart boundary manually:

```ts
const resume = await client.uploadMultipart("/v1/candidates/me/resume", {
  params: { header: { "Idempotency-Key": operationKey } },
  body: { file: new Blob([text], { type: "text/plain" }) },
});
// resume.data is the typed proposed draft; the candidate still confirms profile fields.
```

For authorized resume, evidence, or attachment downloads, use the typed GET with
`parseAs: "arrayBuffer"` and stream from the BFF with attachment/no-store headers.
Evidence access always specifies its exact vacancy scope when required. Do not
cache private files or reuse document URLs across employers. Binary PDF/DOCX
uploads require a live safety scanner; without one they fail closed. Plaintext
resumes produce a draft for confirmation, without silently granting qualifications.
Scanned PDF/DOCX extraction runs in a bounded child process; image-only PDFs,
extraction limits, or unsupported documents yield `MANUAL_ENTRY_REQUIRED` and
require manual profile entry. No OCR or verified qualification is implied.

## Connect existing workflows

| Existing frontend workflow | Backend integration |
|---|---|
| Session/navigation permissions | `/v1/sessions/me`; treat memberships as display state and handle server403 |
| Candidate onboarding/preferences/availability | Candidate GET/PUT, preferences, availability, activation, pause, skills and resume routes |
| Candidate/employer decision cards | Own decision inbox and capacity; submit exact card token and cycle version |
| Organization/team setup | Pending organization, independent verification, invitations, membership approval and per-vacancy ACL |
| Role creation/editing | Versioned vacancies and requirements; edits invalidate dependent agreement readiness |
| PACT prerequisites | Exact role terms/hash, authorized policy, claims, independent verification and recipient-scoped consent |
| Mutual-match pipeline | Match GET, messages, scanned attachments, interview proposals and confirmation |
| Offers/outcomes | Written employer offer, candidate answer, human-reported start and independent start verification |
| Notifications/settings/privacy | Notification pages/preferences and export/deletion request status |
| Administrative/research views | Database-authorized support/operations/research routes; read-only shadow diagnostics |

Always distinguish pending one-sided interest, mutual match, agreement readiness,
accepted offer, and independently verified employment start. Capacity is a maximum
of ten or the user's lower selected limit. Readiness does not create an offer;
offer acceptance does not confirm a start. Research responses remain
`CANNOT_CERTIFY`; do not display a reliability promise, fabricated match percentage,
or automatic hiring decision.

Email/calendar/payment integrations have explicit unconfigured states. Invitations
currently require authorized manual delivery; notification records persist even
when outbound email is unconfigured. Billing cannot affect matching rank.
Account erasure retains necessary audit history and may need provider review.

Local fictional sign-in is an explicit development-only mode, enabled with
`FRONTEND_LOCAL_DEMO=true`, `AUTH_MODE=local` and `ALLOW_DEV_AUTH=true`.
It is limited to loopback hostnames, accepts only the known fictional candidate
and employer fixture names, and stores a short-lived access token in an HttpOnly
cookie. It cannot select verifier/operations fixtures or approve platform roles.
Production builds require configured Supabase authentication.

Mutating BFF requests require a matching Origin/Host and an operation key.
Behind a proxy, set `CAREER_KITCHEN_SITE_URL` to the exact public HTTPS origin;
forwarded host headers are not trusted for CSRF authorization. Reviewed versions
and payloads are retained across exact retries. A 409/412 requires renewed review.

The Pass renders authorized employer decision cards. Unsupported demo taste tests,
private compensation inspection, local-only policy approvals and candidate
self-confirmation of employment have been removed. Invitations expose their actual
manual-delivery token to the authorized administrator; no email delivery is claimed.

The local smoke check is `pnpm smoke:frontend`. Live Vercel cookies, Supabase email
confirmation/refresh, ClamAV, external provider delivery and deployed end-to-end
checks still require actual service credentials and deployment configuration.

