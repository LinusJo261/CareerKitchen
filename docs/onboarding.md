# Saved onboarding

Candidates begin at `/onboarding/candidate`. Five steps collect a display name,
verified account email (read-only), career headline and summary, professional
links, region, desired roles and work arrangements, private compensation minimum,
availability, work and education history, skills, and an optional text resume.
The final review requires separate terms, privacy, and profile-confirmation choices.
It does not infer consent from LinkedIn metadata or previous profile edits.

Names and professional links are owner-visible profile fields. They are omitted
from employer candidate summaries and matching inputs, included in owner exports,
and cleared during account erasure. Minimum compensation remains encrypted and is
never serialized into employer views. History includes an explicit choice about
disclosing each employer's name.

Profiles are saved as drafts; the wizard does not activate introductions. Existing
profiles can return through **Edit full profile**. Employer setup at
`/onboarding/employer` creates an organization pending independent verification;
choosing the employer workspace cannot grant verification or hiring authority.

## Save and resume behavior

The complete reviewed profile is saved before skill changes and optional resume
upload. The UI reports partial completion and retains idempotency keys for uncertain
responses, so retry recovers a committed operation before later edits are saved.
The separate API operations are not one atomic transaction. Incomplete form drafts
are held in the current tab until the user confirms the final review.

The deployment currently supports UTF-8 `.txt` resumes up to 4 MB through the BFF.
PDF/DOCX require the backend's configured malware scanner and remain unavailable
without it. Manual experience and education entry remains available. Resume
contents are stored encrypted in the private bucket; original filenames are not
forwarded to the backend. LinkedIn sign-in supplies basic identity rather than
employment history; see [provider setup](linkedin-sign-in.md).

## Release order

1. Run owner migration `alembic upgrade head` using the separately held migration
   credential. Revision `0006_candidate_onboarding` adds optional `display_name`
   and `professional_links` columns with defaults for existing candidates.
2. Keep restricted API/worker credentials unchanged. The existing table grants and
   row policies cover the new columns. The runtime-role template also ensures the
   schema gate can read the migration revision when metadata RLS is enabled.
3. Deploy API, worker, and Vercel. The API schema/readiness gate expects the new
   revision and continues to reject an unmigrated schema.
4. Verify email signup/sign-in, profile save/reload, export/erasure, and the
   separately configured LinkedIn flow using account-owner credentials.

The session update handles nullable optional Supabase AMR claims and refreshes a
provider-verified legacy HS256 session through Supabase before forwarding an
asymmetrically signed token. It never permits HS256 at the production API. Fixed
server rejection categories support diagnosis without logging credentials or claim
values; live authentication must still be verified on the deployment.
