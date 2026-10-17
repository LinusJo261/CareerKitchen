# ADR 001: backend implementation and safety boundaries

Status: accepted for this implementation.

The workspace had no application repository. The user's request supersedes ZIP
instructions about implementing a frontend or stopping after P0. The backend is a
modular FastAPI application, with SQLAlchemy/Alembic PostgreSQL and persistent
worker processes. No web application or additional password system is created.

Supabase Auth is the production identity authority. Provider claims establish
identity, never application roles. A separately enabled loopback-only development
token CLI supports fictional fixtures. No HTTP endpoint can mint development
tokens or self-assign verifier, signatory or operator privileges.

PostgreSQL outbox rows are also the persistent task queue. `FOR UPDATE SKIP LOCKED`,
consumer receipts, bounded retries, backoff and dead letters provide at-least-once
consumption without a second broker. Idempotency, transition locks and audit are
inside the business transaction. Saved idempotency responses are encrypted and
replays recheck current ownership/roles. Matching computations do not own a write
session; only the transactional executor can introduce people.

Sensitive files use application encryption and private Supabase Storage. Download
proxies recheck permission on every request. This intentionally replaces raw
signed bearer URLs that would remain usable until expiry after consent revocation.
Candidate compensation floors, actual offer terms, cached responses and privacy
exports are encrypted separately from public profile fields.

The core candidate preference fields are colocated with the versioned candidate
profile. Confirmed experience/education records are bounded structured values;
skills, claims, consents, authorizations and lifecycle history remain relational.
Curated immutable feature objects are the only ranker inputs. No protected audit
data is collected here, and no billing or private document content enters ranking.

Original directional formulas and adaptive dual prices are implemented explicitly.
Without observed/calibrated response models, production cold start uses labelled
nonprobabilistic structured relevance. It never fills a probability field with an
invented prior. SQL retrieval is bounded; there is no unlicensed data import or
unapproved embedding service. R99 scenario probabilities must be explicitly
supplied, versioned research assumptions. Global exchanges and WITNESS are bounded
heuristics with abstention, not claims of universal optimality or real reliability.

`GET /privacy/export` reads export status; `POST` requests the job. This avoids a
state-changing GET. Deletion immediately disables identity/matching and grants;
the worker minimizes local data and records external identity/retention review.
Independent start reports and corroboration remain separate from accepted offers.

Rollback uses tested reversible schema migrations only on disposable databases.
Production data changes use the recovery/roll-forward policy in deployment docs.
No pilot execution or statistical certification is enabled by this implementation.
