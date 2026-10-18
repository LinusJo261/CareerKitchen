# Integrating the separately generated v0 frontend

The [Gemini navigation chat contract](navigation-chat.md) describes the read-only
`POST /v1/navigation/chat` endpoint for a separately implemented chatbox, including
server configuration, user consent, authentication, and retry behavior.

The existing Next.js frontend is an interactive preview with fictional, in-memory
workspace data. Career Chef's optional AI conversation uses a server-side bridge;
the other workflows still need an authenticated backend-for-frontend (BFF)
integration before they can operate on real accounts. The runnable contract is
`docs/openapi.json`; Swagger is available at `/docs`, ReDoc at `/redoc`, and the
generated TypeScript interfaces are in `packages/api-client/src/schema.ts`.

## Configuration and authentication

The Next.js application needs its existing Supabase SSR session helper, the public
Supabase project URL/publishable key, and a **server-only** `CAREER_KITCHEN_API_URL`
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

Map the existing pages/forms/buttons to these contracts while preserving the UI.
Live Vercel cookies, Supabase redirects, provider delivery, and deployment smoke
tests require real service configuration and credentials.

