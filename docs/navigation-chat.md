# Gemini navigation assistant

Backend integration for a separately supplied chatbox. No frontend is added.
Set server-only `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-2.5-flash`),
and optionally `GEMINI_TIMEOUT_SECONDS` (default 20). An empty key disables chat.
Choose a model available to your Gemini project before deployment.

`POST /v1/navigation/chat` requires a Supabase bearer token and an
`Idempotency-Key`. Example body:

```json
{"message":"Where can I change my profile?","consent_to_gemini":true}
```

Response `data` contains `reply`, `links` (`label`, `path`), and contract `version: 1`.
The existing write rate limit applies. Reuse the key and exact body for network
retries; changed bodies return 409. No conversation history is stored or sent.
Each message must carry consent. Before enabling Send, tell the user that their
message goes to Google Gemini, and ask them to avoid private or sensitive data.
Only the message and public navigation catalog go to Google; no account records,
resumes, tenant data, bearer tokens or application permissions are included.
Provider data retention is governed by your Google project terms.

Gemini selects topics; the server returns fixed help text and allowlisted paths
from existing pages. Render replies as plain text and links as ordinary navigation.
Links are navigation hints, not authorization; destination APIs retain all ACLs.
The assistant cannot execute actions, accept offers, change consent, override
attention limits, or make matching/reliability claims. Audit/outbox record consent
and references, not chat text. Encrypted idempotency responses follow the existing
seven-day policy. Provider failures return sanitized `503 CHAT_UNAVAILABLE`.
An external API call cannot share the database transaction: after a provider
success followed by a database failure, retry may incur another provider call.

Uses Google's documented [generateContent REST API](https://ai.google.dev/api/generate-content).
After changing endpoints, run `python scripts/export_openapi.py`, then
`npm run generate` and `npm run typecheck` in `packages/api-client`.
