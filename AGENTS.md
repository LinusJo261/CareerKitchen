# Career Kitchen backend

Build backend, infrastructure and integration contracts only. Do not create a
frontend in this repository; the frontend is maintained separately.

Use FastAPI, SQLAlchemy, Alembic and Supabase PostgreSQL/Auth/Storage. Never trust
JWT role metadata for application authorization. Experimental matching stays in
read-only shadow mode; no unsupported reliability certification. Preserve double
opt-in, candidate and vacancy attention ceilings, consent and tenant isolation.
All mutations are transactional, versioned, idempotent, audited and use outbox.
Test each vertical slice before considering it done. Report unexecuted external
checks honestly. Do not commit secrets, fictional outcomes as real, or JTH data.

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
