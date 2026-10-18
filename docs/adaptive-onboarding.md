# Adaptive Career Chef onboarding

Career Chef can prepare an editable candidate profile through conversation. The
website's candidate-onboarding flow calls `POST /v1/navigation/onboarding` through
its server bridge, `/api/navigation/onboarding`. Saving is a separate,
human-confirmed `POST /v1/candidates/me/onboarding` operation. Generating a draft
does not save or activate the candidate, issue an introduction, or grant consent
for matching or evidence disclosure.

Both API operations require authentication and an `Idempotency-Key`. They use the
existing actor-scoped transaction, rate limit, encrypted idempotency, audit and
outbox boundaries. Application permissions come from the database, not JWT role
metadata. Hosted sessions use Supabase; the existing explicit loopback-only local
authentication remains a development fixture.

Synchronous transaction/authentication locks run in a bounded worker pool separate
from FastAPI's dependency workers. ASGI body reads and Gemini waits return to the
event loop, so another request waiting for the same identity cannot freeze health
checks or the provider deadline. Each request keeps one transaction through
commit or rollback; cancelled handlers finish rollback and session cleanup.

## How the conversation adapts

Gemini extracts only preferences and skill names the candidate actually states,
then asks one question. Its instructions narrow vague roles through concrete
tasks, examples, tradeoffs and dislikes. An unclear answer should leave a field
unknown and lead to clarification. An accepted list represents acceptable options,
not a ranked preference or an inferred personality. Broad, explicitly accepted
role lists are permitted; the server does not impose a three-role limit.

The pure server policy in
[`onboarding_planner.py`](../apps/api/app/services/onboarding_planner.py) recomputes
the most useful remaining focus from the updated draft. Its priorities are
engineering choices: occupation/headline, named skills and important job
constraints, primary skill probes, remaining required fields and optional details.
There is no fixed three-step interview or learned information-gain model. Gemini's
returned question must match the server's selected field and, for a probe, the
selected skill. If a valid, safe draft produces an off-policy question, the server
locks the grounded draft and requests one replacement reply/question from Gemini
using the computed focus. That replacement cannot add or change draft fields,
levels or evidence. An invalid replacement fails with sanitized
`503 CHAT_UNAVAILABLE`; the server never fabricates an interview response.

Required profile fields are headline, role families, region, employment types,
work modes, currency and compensation period. Accepting any onsite or hybrid work
also requires explicit acceptable locations, including when remote is accepted
alongside those modes. A home region does not imply acceptable work locations.
Optional compensation minimum and availability may remain unknown.

The draft contains at most eight named skills. The first five receive priority;
this is a conversation bound, not an importance score for employment. A missing
level leads to a named practice probe. The model must present a practical task
and an explicit `Rubric:` before proposing a level from its answer. A proposed
level needs an attributable quotation from a user answer following that named
rubric, plus tentative assessment reasoning. Without that context the server
keeps the level null. Unsupported newly generated evidence is removed.

These checks establish limited conversational provenance, not correctness or
independent verification. The model's rubric and level judgments are informal and
uncalibrated. A user can supply or edit a self-reported level directly. Nothing
here certifies a skill, compares different skills on a validated scale, or predicts
the probability of hiring. History is caller-supplied and cannot attest that a
real assessment occurred.

Known or explicitly skipped questions are not repeated by the server policy.
Skips use a field name, or `skill:` followed by the case-folded skill name with
collapsed whitespace, such as `skill:data analysis`. Skipping a required field
leaves it missing and prevents readiness; it does not invent an acceptable value.
Skipping a skill probe leaves its level unknown. Before final confirmation the
candidate must supply a self-reported level or remove that skill. Corrections
recompute the next focus; completion is not a permanent lock. The review screen
remains editable even without Gemini.

## Draft contract

The authoritative types are
[`schemas/onboarding.py`](../apps/api/app/schemas/onboarding.py). Unknown scalar
values use JSON `null`; unknown lists use `[]`. Undeclared fields are rejected.

| Draft field | Type and bound |
| --- | --- |
| `headline`, `region` | Nullable text; headline 3–180 characters, region 2–160 |
| `role_families` | Up to 20 explicit labels, each 1–120 characters |
| `employment_types` | Subset of `FULL_TIME`, `PART_TIME`, `CONTRACT`, `INTERNSHIP`, `TEMPORARY` |
| `work_modes` | Subset of `REMOTE`, `HYBRID`, `ONSITE` |
| `locations` | Up to 50 explicit labels, each 1–120 characters |
| `compensation_floor` | Nullable nonnegative decimal string; at most 12 integer digits and two decimals |
| `currency`, `compensation_period` | Nullable three uppercase letters; nullable `ANNUAL`, `MONTHLY`, `HOURLY` |
| `skills` | Up to eight distinct `{name, level, evidence, assessment_note}` objects |
| `skills[].level` | Integer 1–5 or null; never a hiring probability |
| `skills[].evidence`, `skills[].assessment_note` | Text up to 2,000 characters each; not a verified credential |
| `summary` | Text up to 10,000 characters |
| `available_from`, `available_until` | Nullable timezone-aware ISO timestamp strings; end must follow start |
| `skipped_fields` | Up to 30 distinct strings, each at most 128 characters |

The chat body contains `message`, literal `consent_to_gemini: true`, `history` and
`draft`. Messages are 1–2,000 characters. History contains at most ten completed
alternating user/assistant pairs; total message/history context is at most 24,000
characters. Individual historical user/assistant messages follow the existing
2,000/4,000-character limits. The full HTTP request is separately bounded.

The response's `data` contains `reply`, `question`, `draft`, `missing_fields`,
`ready_for_review` and `version: 1`. `question` has `field`, `kind`, `prompt`,
optional `skill` and bounded `choices`; kinds are `preference`, `clarification`,
`skill_probe` and `review`. Replies and questions render as text. A model-generated
URL, HTML or invalid contract is rejected rather than executed. An exact
user-provided code quotation in skill evidence is inert text.

Readiness describes draft completeness, not consent, activation, qualification or
eligibility for any vacancy. A skipped required value can lead to a review
question with `ready_for_review: false` so the conversation does not loop.

## Fictional request example

Use a new key such as `fictional-onboarding-001` with a valid session. This example
is a software fixture, not a real candidate, assessment or employment outcome:

```json
{
  "message": "I use Python for small scripts, but I am unsure of my level. Please ask a practical question.",
  "consent_to_gemini": true,
  "history": [],
  "draft": {
    "headline": "Fictional backend developer",
    "region": "Seattle",
    "role_families": ["ENGINEERING"],
    "employment_types": ["FULL_TIME"],
    "work_modes": ["REMOTE"],
    "locations": [],
    "compensation_floor": null,
    "currency": "USD",
    "compensation_period": "ANNUAL",
    "skills": [
      {"name": "Python", "level": null, "evidence": "", "assessment_note": ""}
    ],
    "summary": "",
    "available_from": null,
    "available_until": null,
    "skipped_fields": ["compensation", "availability"]
  }
}
```

Expected behavior is a Python-specific practice question with `Rubric:`, while
the Python level remains null: there is no previous rubric/answer yet. No profile
or confirmed skill is saved. Supply the actual previous prompt in completed
history when answering it, use a new operation key, and review any later level
suggestion. Different model wording is allowed; unsupported grading or a question
for an unrelated field is not. A working provider and a conforming response are
required; this example does not assert that a live request has succeeded.

## Confirmation and matching

[`OnboardingConfirmationIn`](../apps/api/app/schemas/onboarding_confirmation.py)
accepts a normal `CandidateInput` as `profile`, up to eight selected skill
name/level pairs, and literal `skills_confirmed: true`. The profile requires
literal terms/privacy/profile confirmations and the candidate's current
`expected_version` (`0` for a new profile). The website retains its original
resource/version snapshot; background refreshes cannot silently rebase an edited
draft. A stale version requires refresh and renewed review.

The confirmation endpoint saves the actor-owned profile and selected self-reported
skills atomically. It invalidates dependent pending introductions through the
existing profile service, increments versions, audits and writes outbox events.
Skills absent from the request, existing education and experience are preserved
by the website's confirmation payload. Skills return `verification_status:
SELF_REPORTED`. Practice evidence and assessment notes are not saved as confirmed
skill evidence. New profiles remain `DRAFT`; activation is a separate action.

Reuse the same key and exact payload for an uncertain network retry. A completed
replay returns the saved response; a changed payload needs a new key. Keys are
scoped to the authenticated actor and route. Do not automatically update versions,
change answers or resubmit a different operation after a conflict.

The live matcher uses confirmed skill-name coverage with curated aliases and
explicit acceptable role/employment/work-mode preferences, after hard eligibility
checks. It does not consume this conversation's practice grade, evidence text,
assessment note or model confidence. Experience alignment and optional evidence
alignment remain unsupported scoring targets. The separate offline research
pipelines need their own reviewed, point-in-time data and actual outcome labels;
a conversation cannot supply real mutual interest, satisfaction or employment
outcomes. Advanced allocation stays read-only in shadow mode and reliability
remains `CANNOT_CERTIFY`. See [algorithms](algorithms.md) and
[mutual matching research](mutual-matching-research.md).

## Privacy and external boundaries

Before sending, the website shows the editable draft and asks permission to send
answers, completed context and draft keywords/preferences/skill examples to Google.
Draft compensation minimum and availability are excluded unless the separate
sharing choice is selected. Any private information voluntarily typed into an
answer still goes to Google with that message. Do not include secrets, account
details, resumes or sensitive documents. The model is instructed not to solicit
protected attributes or infer personality, legal eligibility or hiring suitability.

The website keeps the transcript and pending retry in page memory; refresh,
unmount or clearing removes that state. Clearing cannot revoke information already
processed by Google. Provider handling is governed by the configured Google
project terms. Closing an in-flight browser request does not prove that the
upstream request was cancelled before processing.

The API stores no separate conversation transcript. Successful encrypted
idempotency responses contain the returned draft, including any quoted evidence,
under the existing seven-day expiration/cleanup policy. Request fingerprints are
keyed; audit/outbox events contain consent and references, not the prompt or
transcript. This is therefore not a promise that no conversation-derived text is
persisted. Final confirmed profile values have their normal application retention.

Provider timeout, quota, unavailable model/key, malformed JSON, unsafe output or
an invalid replacement question returns sanitized `503 CHAT_UNAVAILABLE`. Only a
question-policy failure qualifies for one repair generation; HTTP, schema,
grounding and plaintext failures do not. A request therefore makes at most two
provider calls, both inside the original total Gemini timeout (20 seconds by
default), and each response has the existing 64 KiB decoded-byte cap. The repair
receives only the remaining timeout, not a fresh budget. A completed idempotent
replay makes no new provider call. Both calls may incur provider usage charges.
No fabricated fallback assessment or successful profile save is returned. A provider success
followed by database failure can incur another provider request on retry; external
inference/billing is not part of the PostgreSQL transaction.

## Practical verification matrix

| Case | Expected check |
| --- | --- |
| Vague or several possible roles | Ask one concrete task/tradeoff clarification; do not invent a role, ranked preference or vacancy availability. Preserve an explicitly broad acceptable set. |
| Detailed first answer | Fill only stated values and advance past known fields; no mandatory three-step sequence. |
| Hybrid/onsite, including mixed remote | Ask acceptable locations; do not infer from home region. Empty locations block readiness and confirmation. |
| Python, SQL, C++ or a nontechnical named skill | Use the selected skill and suitable practice/rubric; do not reuse a generic quiz grade or match Java to JavaScript by substring. |
| No prior rubric or invented answer quotation | Keep the level null and remove unsupported evidence; never claim verification. |
| Skip one skill or optional pay/date question | Do not repeat that question; leave unknown values unknown. Required skipped fields still need manual review. |
| Correct a role, mode, location or level | Recompute the next focus and preserve the correction; do not restore an old suggestion silently. |
| Injection asking for secrets, actions or protected-attribute judgments | Treat supplied text as untrusted; grant no permissions, save nothing and expose no account/provider secrets. Review provider wording separately from schema checks. |
| Off-policy question after a valid grounded draft | At most one Gemini reply/question repair against the locked draft and selected focus; preserve unknown levels and all draft values. |
| Timeout, invalid output or invalid repair | Return sanitized 503 within the original total timeout; retry exact saved body/key; no fake answer or partial saved profile. |
| Confirmation exact replay | Same response and replay header; one logical profile/skill change with audit/outbox. |
| Changed retry body or stale candidate version | Respectively 409 idempotency conflict or 412 version conflict; no silent rebase. |
| Different actor with the same key | Separate owned profile/replay scope; neither actor can select the other's candidate. |
| Injected failure during confirmation | Roll back profile, skills, audit, outbox and idempotency together. |
| Decline private-field sharing | Outgoing draft omits pay minimum and dates; manually stored values remain in the editable local draft. |

Focused automated checks live in `test_onboarding_planner.py`,
`test_gemini_onboarding.py`, `test_onboarding_chat_api.py` and
`test_onboarding_confirmation.py`. Run from the repository root with the normal
locked Python environment:

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/tests/unit/test_onboarding_planner.py apps/api/tests/unit/test_gemini_onboarding.py -q
.\.venv\Scripts\python.exe -m pytest apps/api/tests/integration/test_onboarding_chat_api.py apps/api/tests/integration/test_onboarding_confirmation.py -q
```

Integration tests require the configured test PostgreSQL database. Mocked-provider
checks establish software behavior, not live Gemini wording, assessment validity
or browser behavior. Actual Google generation, browser navigation/consent and
hosted Supabase sessions are separate external checks; this guide makes no claim
that those checks have passed.
