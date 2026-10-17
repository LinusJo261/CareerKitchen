# Owner export, erasure and retained records

Career Kitchen processes privacy requests through the PostgreSQL outbox worker.
`POST /v1/privacy/export` queues an owner export; `GET /v1/privacy/export` returns
only the authenticated owner's latest encrypted result. The worker explicitly
allowlists profile/preferences, skills, evidence status and consent records, owned
decision/process/offer statuses, the author's own messages and attachment metadata,
and that user's organization memberships. Private compensation is decrypted only
into the owner's encrypted export. Decision tokens, storage keys, counterpart
message bodies/contact details, and counterpart offer terms are excluded.
Binary documents are available through the separate authenticated document routes
while the account is active; the JSON export states that boundary.

`POST /v1/privacy/delete` requires recent authentication and immediately deactivates
candidate matching and closes candidate interactions. The durable worker then:

- Removes profile biography, location, employment/education history, preferences,
  compensation ciphertext, availability, skills, company blocks and document links.
- Deletes owned resume, evidence and attachment blobs using validated owner-scoped
  references; already-missing blobs count as successful deletion. Wrong-owner
  references stop the job for integrity review instead of deleting another person's
  document. External storage failures use bounded queue retries and dead letters.
- Revokes owned evidence claims, evidence/terms consents, exclusive reservations,
  readiness proofs, memberships and signatory authorizations. Active vacancies
  owned by the disabled account are paused for organizational reassignment.
- Replaces the author's message bodies with a deletion tombstone. Counterpart
  messages remain their own records. Attachment tombstones retain referential
  integrity while their private content is removed.
- Clears prior export ciphertext, cached idempotent response bodies and user
  notifications, clears email and platform roles, and marks the user `DEACTIVATED`.
  The issuer/subject identity tombstone remains so a fresh valid JWT cannot silently
  recreate the disabled account and regain access.

Local erasure results in `NEEDS_PROVIDER_REVIEW`, never an unsupported claim that
Supabase Auth identity, third-party copies, historical backups or retained security
records were erased. An operator must complete provider deletion and document
applicable retention/legal obligations. The implementation does not claim a
jurisdiction-specific retention period or compliance certification.

Append-only audit events, exposure records, process stage events and minimal
relationship identifiers remain as security and hiring-history records. Verified
employment starts and other parties' records are retained separately from active
profile data. Access is scoped; these records must not be reintroduced into live
matching after account deletion. Operational retention schedules, backup expiry,
legal holds and organizational ownership transfers require deployment policy and
human review.

Blob deletion is an idempotent external effect performed for an authorized erasure
request. A later transaction rollback cannot restore an already removed object;
retrying safely treats a missing object as deleted and completes database scrubbing.
Queue errors contain exception classes and reference IDs, never raw export contents.
No raw exported data is placed in outbox or audit payloads.

Uploads can leave orphan blobs when storage succeeds before the database commits.
`app.workers.storage_cleanup.cleanup_local_orphans` provides a dry-run-first local
inventory with bounded deletion batches and a `next_key` cursor. It accepts only
well-formed opaque object keys inside the configured storage root, rejects symlink
or junction redirection, waits at least one day (default seven days), and checks all
candidate resume, evidence and attachment references before deleting anything.
The retention window must exceed application transaction/upload lifetimes. Resume
cleanup on the returned cursor until `next_key` is null. Reference-bearing objects
and recent/in-flight uploads remain untouched. Hosted Supabase cleanup returns
`NEEDS_PROVIDER_INVENTORY_REVIEW`; an operator must obtain a provider inventory and
apply the same reference, retention and ownership checks. This build does not claim
to have erased undiscovered remote orphan objects or backup copies.

Run the worker as a persistent service:

```powershell
.venv/Scripts/python.exe -m app.workers.runner --once
.venv/Scripts/python.exe -m pytest apps/api/tests/workers -q
```

When running outside an installed package, set `PYTHONPATH=apps/api`. Deployment
installs the package, so the module command resolves directly. Email is currently
`NOT_CONFIGURED`; in-app notifications are persisted with opt-ins and current scope
checks. No mail is reported as sent without a configured delivery adapter.
