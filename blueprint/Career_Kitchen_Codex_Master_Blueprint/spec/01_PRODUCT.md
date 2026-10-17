# 01 — Full product specification and state semantics

## Purpose
Career Kitchen coordinates bounded-attention, reciprocal hiring. Candidates don't endlessly apply and employers don't receive unlimited resume spam. The product creates credible, voluntary introductions and tracks them transparently. R99/PACT/WITNESS are **separate opt-in, research-stage subsystems**, not magic guarantees.

## Actors, roles, permissions
- `CANDIDATE`: owns their profile, preferences, evidence claims, opt-ins, blocks, candidate decisions, messages and withdrawal. Can be recruiter separately only with explicit account/tenant separation.
- `RECRUITER`: views own tenant's assigned vacancies and candidates explicitly disclosed for those vacancies; decision authority only where vacancy ACL permits.
- `HIRING_MANAGER`: may decide for assigned vacancy and advance hiring pipeline.
- `ORG_ADMIN`: verifies members, manages own organization, policies and role assignments; only `AUTHORIZED_SIGNATORY` may create formal PACT employer policy authorization.
- `AUTHORIZED_SIGNATORY`: separately recorded status scoped by vacancy/job-policy; authenticated explicitly, not inferred from being recruiter.
- `VERIFIER`: verified third party/operator; may attest evidence source and expiration, but cannot create fake claims or approve hiring.
- `SUPPORT`: only limited, audited support access; no broad candidate evidence retrieval by default.
- `COMPLIANCE_AUDITOR`: isolated aggregate analytics and access logs; sensitive audit columns separated from recommendation code.
- `SYSTEM_WORKER`: machine principal, least privilege, distinct token; may issue cards but no final hiring authorization.

## Candidate journeys
### Candidate onboarding
1. Sign in through OIDC; verify email; accept terms/privacy; age/jurisdiction policy.
2. Create candidate profile: preferred name, summary, role interests, verified/unverified skills, experiences, optional resume, availability window, chosen work types, location and remote/hybrid preferences, private compensation minimum, accepted currencies, authorization attestation for required work jurisdiction if lawful.
3. Parsed resume fields remain *draft* until candidate confirms; keep original file private.
4. Preferences: hard vs soft labels, excluded employers, exposure cap `1..10`, notification choices, availability status. Distinguish work authorization eligibility from citizenship/immigration details; never collect unnecessary protected status.
5. Activate only once required fields and consents are valid. Candidate can pause, update, block companies, export/delete.
6. Inbox shows `Needs decision`, `Waiting`, `Mutual matches`, `Interviews`, `Offers`, `History` as separate groups. Only `Needs decision` counts toward ten-card cap.
7. Card displays pay range, role, employer, work arrangement, why relevant, who expressed interest, trustworthy evidence indicators, expiration, Interested/Pass buttons. No opaque global percentage.
8. With mutual interest, access chat, interview scheduling, offer timeline and process outcome; candidate can withdraw at any point.

### Employer onboarding
1. OIDC sign-in, organization create/join, legal business/work-email verification, assign org admin and hiring signatory explicitly.
2. Create vacancy draft: title, description, pay range, currency, employment type, work mode, location, number of openings, responsibilities, required vs preferred skills, lawful/essential requirements, experience, hours, interview stages, start window, compensation constraints, recruiter owner, role close/deadline.
3. Human reviews essential requirement classifications and discriminatory wording; inaccessible fields or unverified requirements block activation until correction.
4. Activate vacancy; see per-vacancy candidate decision inbox up to 10, waiting, shortlists/possible pipeline. Candidate private compensation exact floor stays hidden unless explicitly disclosed.
5. Employer may configure PACT rule with authorized signatory: scope exact vacancy + immutable version + salary range, location, responsibilities, start window, required evidence and permitted conditional agreements. One approval doesn't automatically cover other jobs.
6. Review candidate in card; Interested/Pass. Mutual enables chat. Track interview, offer, rejection or completed employment start (with source and independent attestation if possible). Closing vacancy invalidates all pending decisions.

## PACT agreement semantics
- Candidate confirmation means 'I am willing to proceed on these displayed terms subject to further decisions' NOT irrevocable obligation or job acceptance.
- Employer authorization means a human with actual decision authority approved a specific ruleset and stage of evaluation. In a true preauthorization, precisely define whether it authorizes interviews, conditional offers, or something else; never infer offer/hire.
- Evidence claim: verifier, method, source, statement, verified_at, expires_at, revoked_at; may be private reusable fact but employer-specific disclosure is separately consented.
- Readiness proof: short-lived, signed or hash-linked attestation that *current terms, role version, authority, evidence and consent align*; always recheck live state before displaying. Proof is not actual hire.
- A revocation or role edit invalidates all derived readines proofs and pending unexecuted plans.

## Key user experience distinctions
- `internal research shortlist`: planned candidate set hidden from all humans; not counted as delivered.
- `employer-visible candidate`: actually shown in employer interface; counts as delivered for that vacancy when delivery logged.
- `active decision`: action request awaiting one human; counts against that human/scope active-cap.
- `waiting`: first mover has already expressed interest; waiting for other-side slot; does not count as active decision.
- `mutual`: both sides interested, not hired.
- `offer_accepted`: signed/confirmed offer, NOT necessarily started.
- `verified_start`: completed employment start verified by acceptable sources, used for reliability evaluation.
- `exclusive_reserve`: optional candidate-approved time-bound allocation/hold, scarce across vacancies; never silently reserve.

## Pair state machine
Core canonical state progression:
```
ELIGIBLE -> CANDIDATE_DECISION_REQUIRED | EMPLOYER_DECISION_REQUIRED
CANDIDATE_DECISION_REQUIRED + C.Interested -> CANDIDATE_INTEREST_SENT -> EMPLOYER_DECISION_REQUIRED or WAITING_EMPLOYER_SLOT
EMPLOYER_DECISION_REQUIRED + E.Interested -> EMPLOYER_INTEREST_SENT -> CANDIDATE_DECISION_REQUIRED or WAITING_CANDIDATE_SLOT
second-side Interested -> MUTUAL_MATCH
MUTUAL_MATCH -> INTERVIEWING -> OFFERED -> OFFER_ACCEPTED -> START_CONFIRMED
any permitted state -> CLOSED_PASS | CLOSED_EXPIRED | CLOSED_WITHDRAWN | CLOSED_JOB_CLOSED | CLOSED_FILLED_ELSEWHERE | CLOSED_REJECTED | CLOSED_ADMIN
```
The first interested side *must not* grant match without second side's explicit interest. Only valid transition via state-machine module under DB transaction; every transition is versioned and audited. `START_CONFIRMED` is a separate externally evidenced event, never inferred from offer acceptance.

## Notifications
Email or in-app for a newly issued decision, near-expiry (max two reminders), mutual match, message, interview, offer, status updates, PACT approval/decline, consent revocation, admin actions. Notify only to users entitled to see event, with no sensitive details in push text. Suppress stale notifications based on latest cycle state. Preference opt-outs respected except legal/security notices.

## Messaging and scheduling
Messaging only after `MUTUAL_MATCH`; sanitized text; attachment scanning and media ACL; block/report. Scheduling allows proposing 2–5 candidate times without reading external calendars unless user connects and authorizes calendar. Invites idempotent, avoid overlapping confirmed bookings. Offer letter / employment stage not set by chat message.

## Dashboard metrics
Candidate: active decision capacity, waiting items, mutual matches, upcoming interviews, offer statuses, settings and privacy; employer: active vacancies, response throughput, time-to-first-review, pipeline stages, attention usage and confirmed starts. Internal audit: rejection/timeout calibration, model drift, fairness review (aggregated, restricted). Never display '99.9% guarantee'.

## Anti-abuse and trust
Detect duplicate/fake employers and roles, misleading compensation, mass spam, candidate impersonation, suspicious attestations, fake documents, message harassment, coerced acceptance, and attempts to use hidden attributes in selection. Reporting + appeal flows with human resolution. Rate limit invitations, messages, and bulk operations. Add explicit employer override if system suggestions don't fit, with logged reason and no silent model retraining from arbitrary bias.

## Non-goals for initial build
No autonomous applications, scraped profiles, fake references, automatic binding contracts, undisclosed algorithmic final rejection, general background checks, real-time guaranteed hiring, paid match placement, online marketplace for unsolicited DMs, resume spam, or mandatory universal active-card count of 10.

## The exact meaning of 'n candidates to a company'
At most ten **simultaneous active employer decision cards per vacancy** (and at most ten for a candidate globally) is a concurrent UI and attention ceiling; it does **not** mean at most ten candidates can ever be shown to one employer. Career Kitchen may sequentially show additional people when earlier cards resolve, subject to deadlines, consent, budgets and anti-spam limits. `n_delivered` counts all distinct employer-visible candidates over a predefined hiring horizon. The planner may initially set `n=0` when there is no credible opportunity, or reserve a longer ordered contingent plan whose later members are *not* counted as delivered unless actually shown. Optimize smallest useful *actual delivery count*, not easiest denominator manipulation.
