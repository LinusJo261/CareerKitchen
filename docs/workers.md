# Durable background processing

`python -m app.workers.runner` runs the persistent PostgreSQL worker. `--once`
processes one bounded maintenance pass and up to fifty events; `--batch-size`
accepts `1..200`. It is not an unbounded drain command. `WORKER_POLL_SECONDS`
controls idle polling. Railway should run this as a separate persistent service
using the same application database/schema as the API.

Each event is selected with `FOR UPDATE SKIP LOCKED` and processed in its own
transaction. A successful business mutation, notification item, `InboxConsumption`
deduplication row and dispatched marker commit atomically. A nested savepoint
rolls back the handler's effects on failure, while the outer transaction records
the attempt, exception class and exponential backoff. Five failed attempts produce
a durable dead letter. Operators must inspect the cause and explicitly requeue;
the worker does not silently reset poisoned jobs. Logs exclude payload contents.

The worker stores a dedicated `SYSTEM_WORKER` identity under an internal issuer.
The public Supabase JWT verifier cannot mint or authenticate that identity. Its
database identity can be disabled operationally; it is not a recruiter/signatory.
It cannot express human interest, approve a hiring policy, send a human message,
or verify employment automatically.

Reconciliation is triggered by materially relevant candidate/vacancy changes,
answers/expiry, evidence/consent changes and price windows. The baseline executor
retains its locks, feasibility checks, cooldowns, chosen lower caps and outbox
audit. A generated `decision.issued` event creates a notification only and cannot
recursively trigger more clearing. Pending decisions with stale role terms or
missing essential eligibility close; human mutual commitments remain intact.
An explicit `shortlist.replan_requested` is a separate research event: consumption
commits first, then records read-only shadow diagnostics when SHADOW is enabled.
It never calls live clearing, issues a card or creates a human notification.

Periodic work runs even when the outbox was empty: expire cards/waiting,
reservations/readiness/clarifications, record timed evidence/consent expiry without
inventing a user's revocation, release eligible waiting interest, and enqueue at
most two reminders in the final 24-hour and 12-hour windows. All batches are
bounded. Every currently expired consent/evidence reference gets one durable
expiry event; time checks also reject stale access synchronously before a worker
arrives. Persistent attention/congestion windows are documented in
[algorithms.md](algorithms.md).

Notification recipients are re-derived from current card/match ownership and
organization membership plus vacancy ACL, never event-provided user IDs. Stale
cards, changed terms, revoked membership, inactive accounts and in-app opt-outs
suppress delivery. Private document contents and message bodies stay behind their
authenticated services. The email adapter is not configured; records explicitly
say `NOT_CONFIGURED` and never claim an email was sent. This build does not claim
external calendar or email delivery.

In `FEATURE_MODE=SHADOW`, the baseline transaction commits first. A separate
authorized snapshot builder collects only sanctioned derived inputs and current
price/role/profile versions, then closes its database session. The pure planner
receives only frozen objects. A separate recorder writes `ShadowRun` diagnostics;
planner exceptions or budget exhaustion cannot roll back or alter baseline
decisions. A crash between baseline commit and research recording can omit a
shadow diagnostic; research results are not a correctness dependency or a public
claim. The package ships without empirical scenario models or a public reliability
validator, so all claims remain `CANNOT_CERTIFY`.

The worker implements encrypted owner export and local erasure as described in
[privacy.md](privacy.md). Supabase provider identity deletion and remote orphan
inventory remain explicit operator review steps. No data is claimed erased beyond
the operations actually completed.

Tests use unique temporary schemas in `career_kitchen_test` on real PostgreSQL,
cover parallel SKIP LOCKED consumption and deduplication, rollback/retry/dead
letters, idle expiry and waiting release, scoped notifications, bounded reminders,
shadow parity/failure isolation, persisted dual updates, owner-only export and
local erasure, fresh-login rejection, and retention-aware orphan cleanup:

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests/workers -q
```
