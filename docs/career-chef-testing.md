# Test the Career Chef website and API

Career Chef uses the existing FastAPI Gemini integration at
`POST /v1/navigation/chat`. The existing Next.js website now has a floating
**Ask Chef** button and a dedicated `/career-chef` page. The website calls the
same API through a server-side bridge at `/api/navigation/chat`.

## Test the website

Open **http://127.0.0.1:3000/career-chef** for the standalone chat, or
**http://127.0.0.1:3000** for the existing website with its floating chat button.

1. Check the consent box to send your question and recent conversation to Google.
2. Ask `Where can I find job opportunities?` and select **Send question**.
3. Follow a suggested page link, or ask a follow-up question.

Conversation and optional session tokens stay in tab memory, including when you
close/reopen the chat or follow a page link. Refreshing clears that memory.
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
API is reachable; send a question to verify actual Gemini generation.

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

The API walkthrough covers PostgreSQL startup, migrations, and environment setup.
For this workspace's recovered offline Python runtime, use this API command
instead of the broken original `.venv`:

```powershell
$env:PYTHONPATH = 'apps/api;.'
$env:PATH = (Join-Path $PWD '.local\postgres\pgsql\bin') + ';' + $env:PATH
$env:PSYCOPG_IMPL = 'python'
.\.local\venv312\Scripts\python.exe -m scripts.local_dev serve
```

The recovered runtime passes the focused API tests, but it is not a clean
installation of `requirements.lock`. Use a normal locked installation on a fresh
machine. Runtime caches and credentials stay ignored by Git.

## Website connection and authentication

`CAREER_KITCHEN_API_URL` optionally configures the server-side API base URL; it
defaults to `http://127.0.0.1:8000`. It accepts HTTPS or a loopback HTTP address.
Changing it requires restarting Next.js.

In Next.js development mode only, when `.env` explicitly selects
`ENVIRONMENT=development`, `AUTH_MODE=local`, `ALLOW_DEV_AUTH=true`, and a valid
local signing secret/issuer, loopback website requests use a short-lived fictional
website tester identity. This identity has no application roles and is distinct
from the CLI tester. FastAPI still authenticates and transactionally processes
each request with its existing limits and audit behavior.

Production builds and hosted APIs require a real bearer access token. For manual
testing, expand **Connection details** and enter a valid session token. Existing
demo sign-in forms do not authenticate with the API. The bridge does not return
JWT signing secrets or Gemini keys to the browser.

## Verification

```powershell
pnpm typecheck
node --test scripts/test-navigation.cjs
python -m pytest apps/api/tests/unit/test_navigation.py apps/api/tests/unit/test_navigation_origins.py apps/api/tests/integration/test_navigation_api.py
```

The frontend regression suite tests transport and authentication guards, retry
payloads, history budgets and safe links. Backend tests include real PostgreSQL
transactions with mocked Gemini HTTP responses. Live Google generation requires
the configured key and is a separate check.
