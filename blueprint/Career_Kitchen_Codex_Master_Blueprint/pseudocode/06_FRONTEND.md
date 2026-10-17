# 06 — Complete Career Kitchen frontend pseudocode (Next.js / React / TypeScript)

## Frontend conventions and shared UI contracts
- Brand: Career Kitchen. Accessible, minimalist and credible; optional kitchen metaphor limited to product naming and a few microcopy choices, not cartoonish employment claims.
- Public users see NO probability guarantee, no false hiring badge, no opaque desirability score. Internal debug/research results are separately authenticated.
- Use App Router server components for initial data, client components for interactive forms and cards. Strongly typed API client generated from FastAPI OpenAPI. Zod validation duplicated at client but backend always authoritative.
- Server Actions and route handlers must reauthorize every operation; direct API mutations protected the same way. Never put bearer tokens in browser localStorage; use secure server sessions.
- Design states: loading, empty, forbidden, expired, stale version, low connectivity, optimistic pending, success, failure, read-only, consent revoked, unverified.
- WCAG-oriented: keyboard, focus trap for dialogs, labeled forms, visible validation, semantic HTML, contrast, reduced-motion, screen-reader announcements, large tap targets.

## Target page tree
```
/                          Landing (value proposition, waitlist/demo)
/how-it-works              Transparent two-sided flow
/privacy /terms /accessibility
/sign-in /auth/callback /onboarding/choose-role
/candidate/onboarding/{profile,preferences,skills,verification,review}
/candidate/dashboard
/candidate/decisions
/candidate/waiting
/candidate/matches
/candidate/matches/[id]       Conversation + stage + scheduling
/candidate/offers/[id]
/candidate/evidence
/candidate/settings/{privacy,notifications,blocks,data}
/employer/onboarding/{organization,verify,team}
/employer/dashboard
/employer/vacancies
/employer/vacancies/new
/employer/vacancies/[id]      Vacancy status, decision inbox, pipeline
/employer/vacancies/[id]/edit
/employer/vacancies/[id]/pact
/employer/vacancies/[id]/candidates
/employer/vacancies/[id]/matches
/employer/organization/{team,settings,verification,billing}
/admin/{moderation,verification,audit,pilots} (restricted)
/demo                      Sample market only, clearly fictional
```

## Shared navigation/layout pseudocode
```tsx
function AppRoot({children}) {
  session = serverGetVerifiedSession();
  use safe theme fonts/icons; provide locale & timezone, error boundary,
      reduced-motion preference, toast system, auth-aware navigation;
  if !session show PublicNav else show role-scoped CandidateNav or EmployerNav;
  render children and live-region notifications;
}

function NavLink({route}) {
  show only if backend capability check allows;
  NEVER rely on nav hiding as RBAC enforcement;
}

function AsyncMutationButton({action,expectedVersion,idempotencyKey}) {
  click -> locally mark pending -> invoke authorized server action/API;
  on 409/412 -> refetch latest state; show 'changed since last view';
  on 422 -> inline errors; on 403 -> no state change; on 429 -> rate limit message;
  on success -> invalidate query + update announcement;
  prevent duplicate clicks, but server idempotency remains mandatory;
}
```

## Candidate onboarding wizard
```tsx
function CandidateOnboardingWizard() {
  step = 0..4; draft = useForm(schemaPerStep);
  0 Identity & role interests: role families, region, desired work mode;
  1 Experiences and skills: resume upload optional, editable parser suggestions,
    skills with clear self-reported vs verified badges;
  2 Terms: salary min private, location constraints, availability and caps;
  3 Privacy & evidence: who can see data, verified claim disclosures opt-in,
    block organizations, data export info;
  4 Review: terms/privacy consent, activate profile;
  Save each step to owned profile via versioned PUT; if failed, preserve draft locally
  in memory only for sensitive data; never publish raw file by accident;
  end -> candidate.dashboard.
}
```

## Candidate dashboard, decision inbox, consent
```tsx
function CandidateDashboardPage() {
  data = await api.get('/candidate/summary');
  show ActiveDecisionCounter(`${count}/${selectedCap}`), WaitingCounter,
       MatchesUpcoming, InterviewEvents, OfferStatusList, ProfileCompleteness;
  quick links to consent and pause matching; no global 'candidate rank'.
}

function CandidateDecisionCard({card}) {
  show employer verified status, title, salary band, work mode, location,
       role reasons, other side Interested status, expiry countdown,
       evidence requirements if reasonable and user-viewable;
  Interested and Pass; request confirmation of voluntary action;
  submit POST /v1/decisions/:id/(interested|pass) with version and idempotency;
  on accepted: card moves out of Active, Waiting/Match stage appears;
  on stale: update card and do not replay click implicitly;
}

function EvidenceConsentModal({claim,role}) {
  retrieve exact target employer + vacancy + role version + claim + disclosure extent;
  show summary vs actual document options; opt-in checkbox initially unchecked;
  POST /v1/consents/evidence; show current grants with explicit revoke control;
  do not open media until short-lived ACL token validated;
}

function CandidateTermsReview({role}) {
  show confirmed salary terms, work mode, role duties, authorization context,
       notice that agreement readiness != job offer or obligation;
  POST candidate term consent with roleVersion, termsHash, expiry;
  allow revoke; notice when role terms change and require new consent;
}
```

## Employer journey and PACT editor
```tsx
function OrganizationSetupWizard() {
  collect org name, work email, legal entity verification details;
  show pending verification state; permit draft roles but no real activation until verified;
  member invitation flow with RBAC and expiration; no privilege escalation.
}

function VacancyEditorPage({vacancyId?}) {
  fields: title, description, pay low/high, currency, number openings,
          work mode/location, role family/seniority, skills, start window,
          essential vs preferred vs ambiguous requirements, recruitment owner;
  validation and warning on possibly discriminatory language;
  preview candidate-facing role; Save Draft; Activate (requires server check);
  editing active role terms shows consent/readiness invalidation confirmation.
}

function EmployerVacancyDashboard({id}) {
  show role version/active status, active employer decisions < 10,
       waiting, mutual matches, pipeline; read-only shadow report only for pilot-admin;
  show 'What is missing?' actionable readiness reasons (no raw private attributes),
       PACT authorization wizard, shortlists only if pilot explicitly enabled.
}

function EmployerCandidateCard({candidateCard}) {
  show disclosed identity only within scope, work fit, skills proof summary,
       relevant experience, approved compensation alignment boolean,
       candidate already interested indicator, expires_at, Interested/Pass;
  do NOT show candidate exact private salary floor, hidden rejection reasons,
      protected fields, raw claim document unless explicit role-specific grant;
  use same versioned idempotent decision endpoint.
}

function PACTPolicyWizard({role}) {
  step 1: show current immutable vacancy role_version and terms hash;
  step 2: classify essential/preferred/ambiguous requirements; require human review;
  step 3: choose specifically authorized decision stage (screen / interview / conditional offer);
  step 4: show exact role IDs covered and compensation + evidence requirements;
  step 5: signatory re-auth step-up and confirm signed authorization;
  step 6: display active scope, expiry, revocation, changes invalidate old proofs;
  no auto-filling a final employment decision, no implied offer;
  if unauthorized signatory -> show request admin access workflow, not silent approval.
}

function PolicyClarificationDialog({proposal}) {
  show which exact requirement, jobs and versions affected, candidate privacy protections,
       question text, why it was asked, choices Approve/Deny/Review Later;
  never say answer 'guarantees a hire'; no automatic approval;
  POST approved exact scope; only then trigger matching replan.
}
```

## Matches, chat, schedule, offer workflow
```tsx
function MatchWorkspace({matchId}) {
  require mutual match from server; websocket or polling subscribed to own match only;
  tabs: Conversation, Interview, Timeline, Offer, Files;
  show opt-out, report, withdraw and escalation action;
}
function MessageComposer() {
  validate length & attachment types; POST message; use client temp ID;
  reconcile server authoritative message and timestamps; sanitize markdown;
  disable if match closed, permissions revoked, rate-limited;
}
function InterviewScheduler() {
  show options in viewer timezone; allow candidate/employer to propose and accept;
  double-check conflicts before confirmation; offer manual meeting link;
  calendar connector optional and separate OAuth consent;
}
function OfferView() {
  display versioned actual offer, compensation, start date, expiry, document;
  candidate explicitly accept or decline; label Accepted Offer != Started Job;
  employer process tracking cannot claim verified start without corroboration;
}
```

## Admin and research pages
```tsx
function ResearchPanel() {
  admin-only; show Mode=BASELINE/SHADOW/PILOT, planner runtime, mean attention,
  counterfactual suggestions, action rejection reasons, simulated-only metrics;
  on model risk display big 'RESEARCH ESTIMATE — NOT RELIABLE CERTIFICATION';
  show data provenance and full cohort denominator; no ranking of actual persons by
  protected attributes or global desirability;
  forbid 'enable pilot' from page without additional approved governance workflow.
}
function ModerationConsole() {
  limit to permissioned support actions, audit all views, resolve fraud and reports,
  preserve appeal evidence without granting broad candidate evidence access.
}
function AccessibilityAndPrivacy() {
  candidate can inspect evidence grants, revoke, block org, pause, download/delete;
  fix mistaken claims/offer statuses with contest process;
}
```

## Demo UX — Career Kitchen presentation
```tsx
function GuidedDemo() {
  display persistent 'Fictional Demo Market' ribbon;
  Scene A: Employer creates role + classifies requirements + PACT policy stage;
  Scene B: Candidate confirms compensation and evidence scope;
  Scene C: readiness proof with clear conditions/expiry and no hire guarantee;
  Scene D: candidate and employer independently choose Interested;
  Scene E: simulated market shows why top-N can collide or share risks;
  Scene F: research-only global shortlist + WITNESS question (approve / deny branches);
  Scene G: dashboard displays delivered n, attention spent, genuine funnel counts;
  highlight comparisons only where computed by fixture and label synthetic;
  reset demo deterministically with seed, no invented live company references.
}
```

## Shared UI components and state
```
AccessibleDialog, FormField, ErrorSummary, ConfirmAction, AsyncState, Toast,
CandidateCard, VacancyCard, DecisionCounter, Deadline, EvidenceBadge,
SalaryRange, ConsentLedger, PolicyVersionBadge, ReadinessStatus,
ShortlistScenarioVisualization (admin only), Timeline, NotificationInbox,
InterviewCalendar, AuditStatus, RoleRequirementEditor, ProtectedInfoWarning,
ConnectionStatus, ProfileStrength (completeness not employability), Skeleton,
EmptyState, PermissionDenied, StaleObjectBanner, FileUploadWithScanStatus.
```

## Frontend test outline
- Component: keyboard-only complete onboarding, errors announced; no secret leak in component props.
- Tenant: employer A cannot access employer B pages even by guessing URL; server responds 403.
- Consent: revoked claim no longer visible; stale signed URL inaccessible after appropriate revalidation.
- State: duplicate Interested click handled once; card disappears; mutual unlock only after two genuine decisions.
- Role edit: candidate sees terms changed, must re-acknowledge; cannot use stale PACT proof.
- Mobile: screens at narrow widths; touch targets and scroll, fixed buttons do not cover action cards.
- Demo reset: two runs yield same fictional state trace.
