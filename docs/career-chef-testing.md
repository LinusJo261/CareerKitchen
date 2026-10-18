# Test the Career Chef website and API

Career Chef includes an on-site quick guide and an optional AI conversation.
The Next.js website has a floating **Ask Chef** button and a dedicated
`/career-chef` page. The AI conversation calls the existing FastAPI Gemini
integration at `POST /v1/navigation/chat` through the server-side bridge at
`/api/navigation/chat`.

## Test the website

Open **http://127.0.0.1:3000/career-chef** for the standalone chat, or
**http://127.0.0.1:3000** for the existing website with its floating chat button.

1. Open the floating assistant and use **Quick guide** to choose candidate or
   employer help. Check that the next-step links reach the relevant pages. This
   authored guide works without an API session, Google consent, or a Gemini call.
2. Switch to the AI conversation. Check the consent box to send your question and
   recent conversation to Google. Connect an API session first when required.
3. Ask `Where can I find job opportunities?` and select **Send question**.
4. Follow a suggested page link, or ask a follow-up question.

The quick guide is fixed application guidance. It is not a generated response or
confirmation of account activity. Neither mode completes onboarding, updates
profiles, sends messages, or makes decisions for the user.

Conversation, draft, consent and optional session tokens stay in tab memory,
including when you close/reopen the chat or follow a page link. The selected
quick guide resets when its panel remounts. Refreshing clears the tab memory.
**Clear conversation** removes the chat. Failed messages have an explicit retry
button that resends their original body and idempotency key.

The API stores encrypted successful idempotency responses under its existing
retention policy. Google processes the messages you consent to send; see
[the backend privacy and retry details](navigation-chat.md).

## Configure Gemini

Put your Google API key in the repository's ignored `.env` file:

```dotenv
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-3.8-flash
```

Create a key in [Google AI Studio](https://aistudio.google.com/api-keys).
Restart the FastAPI server after changing the key. The key belongs only on the
server; do not enter it in the chat's session token field or prefix it with
`NEXT_PUBLIC_`. The integration uses Google's
[generateContent API](https://ai.google.dev/api/generate-content).

The backend reports `503 CHAT_UNAVAILABLE` until a working key/model is configured.
There are no generated fallback answers. A successful health check confirms the
API is reachable; it does not verify that the chat endpoint exists or that a
working Gemini key/model is configured. An older connected service may answer
`/v1/health` while returning `404` or `405` for `/v1/navigation/chat`. The website
maps those missing-endpoint responses to a safe `503 CHAT_UNAVAILABLE` message
and leaves the quick guides available. Check the connected API's OpenAPI
documentation for `POST /v1/navigation/chat`, then send an authenticated,
explicitly consented question to verify actual Gemini generation.

## Test the API independently

Open **http://127.0.0.1:8000/docs**, authorize, then expand
**POST /v1/navigation/chat**. Use a new `Idempotency-Key`, for example
`individual-test-001`, and this request body:

```json
{
  "message": "Where can I find job opportunities?",
  "consent_to_gemini": true,
  "history": []
}
```

Read the generated answer in `data.reply` and suggested destinations in
`data.links`. Repeat the exact request with the same key to test replay; use a new
key for a changed question. Authorization is required even for navigation help.

For explicitly configured local development, `python -m scripts.local_dev token`
prints a short-lived fictional test token. Follow
[the API walkthrough](navigation-chat.md) for local setup or use a real Supabase
session in hosted environments. Swagger adds `Bearer` automatically.

## Start each service separately

From the repository root, with Node/pnpm and the Python dependencies installed:

```powershell
# Website, separate terminal
pnpm dev --hostname 127.0.0.1 --port 3000

# API, separate terminal; PostgreSQL must already be running and migrated
.\.venv\Scripts\python.exe -m scripts.local_dev serve
```

The [API walkthrough](navigation-chat.md) covers PostgreSQL startup, migrations,
and environment setup. Use a Python environment installed from
`requirements.lock`; runtime caches and credentials stay ignored by Git.

If the separate fictional demo service already occupies port 8000, preserve it
and run the current chat-enabled backend on another loopback port:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Set `CAREER_KITCHEN_API_URL=http://127.0.0.1:8001` in the ignored `.env` file and
restart Next.js. This backend uses the main configured database; the fictional
demo service keeps its own database. Do not change the JWT issuer just to match
the new serving port. The browser bridge forwards requests without an Origin
header; direct Swagger tests on port 8001 need that exact origin in the API's
`CORS_ORIGINS` configuration.

## Website connection and authentication

`CAREER_KITCHEN_API_URL` optionally configures the server-side API base URL; it
defaults to `http://127.0.0.1:8000`. It accepts HTTPS or a loopback HTTP address.
Changing it requires restarting Next.js.

In Next.js development mode only, when `.env` explicitly selects
`ENVIRONMENT=development`, `AUTH_MODE=local`, `ALLOW_DEV_AUTH=true`, and a valid
local signing secret/issuer, loopback website requests use a short-lived fictional
website tester identity. Both the request URL and incoming Host must identify a
loopback address; a normalized localhost URL does not enable this identity for a
LAN or hosted Host. Forwarded Host headers cannot enable local authentication.
Keep the development server bound to loopback. This identity has no application
roles and is distinct from the CLI tester. FastAPI still authenticates and
transactionally processes each request with its existing limits and audit
behavior.

Production builds and hosted APIs require a real bearer access token for the AI
conversation. For manual testing, open the full `/career-chef` page, expand
**Session connection**, and enter a valid session token. Existing demo sign-in
forms do not authenticate with the API. The quick guide remains available without
that setup. The bridge does not return JWT signing secrets or Gemini keys to the
browser.

## Verification

```powershell
pnpm typecheck
node --test scripts/test-navigation.cjs
python -m pytest apps/api/tests/unit/test_navigation.py apps/api/tests/unit/test_navigation_origins.py apps/api/tests/integration/test_navigation_api.py
```

The frontend regression suite tests transport and authentication guards, local
identity restrictions under normalized Host headers, sanitized errors, retry
payloads, Unicode history budgets and safe links. Backend tests include real
PostgreSQL transactions with mocked Gemini HTTP responses. Live Google generation
requires the configured key and is a separate check.

For browser verification, check the following flows on desktop and a narrow
mobile viewport:

- Open, close, and reopen the bottom-right assistant. Escape returns focus to its
  launcher. The panel is nonmodal: the underlying page remains interactive and
  keyboard focus can move between the assistant and page.
- Use the quick guide without granting Google consent, then follow an onboarding
  link. Verify that route changes retain the conversation, draft, consent and
  optional session token in tab memory; reopening the guide starts at its list.
- Switch to AI, enter a starter question, and verify that sending remains disabled
  until explicit consent. Enter sends; Shift+Enter adds a line; IME composition
  does not submit prematurely.
- Force an offline or provider-unavailable response. The saved question stays
  visible, retry reuses its exact body/key, and no fabricated answer appears.
- Clear a pending request, then allow its response to finish. The cleared chat
  must stay empty. Closing the widget alone should preserve the question.
- Check a 2,000-character question, an over-limit question, a long reply, and a
  follow-up. Text and page links must wrap without horizontal overflow.
- Refresh the page to clear the transcript, draft, consent, and optional token.

These checks are a verification checklist, not a claim that a live Gemini or
hosted Supabase session was tested.
