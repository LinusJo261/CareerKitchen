// Frontend view-model contracts. When the FastAPI OpenAPI schema is available,
// regenerate or align these types with it — the backend remains authoritative.
export type Role = 'candidate' | 'employer'
export type Decision = 'interested' | 'passed'
export type Stage = 'Mutual interest' | 'Interviewing' | 'Offer' | 'Employment confirmed'
export type PipelineStage = 'Introduced' | Stage
export type RequirementWeight = 'Must-have' | 'Preference' | 'Flexible'

export interface CandidateProfile {
  id: string
  name: string
  title: string
  location: string
  skills: string[]
  summary: string
  /** Active decision capacity, 1–10. Not a lifetime limit. */
  capacity: number
  availability: string
  experience: string
  compensation: string
  remote: string
  privacy: boolean
  industries?: string[]
  roles?: string[]
  requirements?: Record<string, RequirementWeight>
}
export interface Organization { id: string; name: string; verified: boolean; description: string; domain?: string; verification?: 'Verified' | 'Pending' | 'Not started' }
export interface Vacancy {
  id: string
  title: string
  company: string
  salary: string
  location: string
  arrangement: string
  skills: string[]
  summary: string
  deadline: string
  verified: boolean
  employerInterested: boolean
  status: 'Active' | 'Draft' | 'Closed'
  employmentType: string
  responsibilities?: string[]
  required?: string[]
  preferred?: string[]
  experience?: string
  startWindow?: string
  workflow?: string[]
}
export interface Opportunity extends Vacancy { reason: string }
export interface MutualMatch { id: string; opportunityId: string; name: string; role: string; company: string; stage: Stage; updated: string }
export interface PipelineEntry {
  id: string
  name: string
  title: string
  vacancy: string
  stage: PipelineStage
  interest: 'Mutual' | 'Awaiting candidate' | 'Awaiting you'
  updated: string
  verifiedEvidence: number
  skills: string[]
}
export interface PactPolicy {
  id: string
  role: string
  version: string
  compensation: string
  arrangement: string
  requirements: string[]
  evidence: string[]
  stages: string[]
  authority: string
  expires: string
  revocation: string
  status: 'Draft' | 'Authorized' | 'Revoked'
  candidateConfirmed: boolean
}
export interface ConsentRecord { id: string; label: string; recipient: string; purpose: string; expires: string; granted: boolean }
export interface VerificationSummary { id: string; name: string; status: 'Verified' | 'Pending' | 'Not shared'; issuer: string }
export interface ClarificationRequest {
  id: string
  kind: 'Requirement clarification' | 'Missing attestation' | 'Decision-maker unavailable' | 'Terms mismatch'
  title: string
  description: string
  why: string
  action: string
  status: 'Pending' | 'Approved' | 'Rejected'
}
export interface Interview { id: string; side: Role; company: string; role: string; person: string; date: string; time: string; format: string; status: 'Scheduled' | 'Reschedule requested' | 'Confirmed' }
export interface Offer { id: string; company: string; role: string; salary: string; deadline: string; start: string; status: 'Awaiting response' | 'Accepted' | 'Declined' }
export interface Notification { id: string; side: Role; title: string; description: string; read: boolean; href?: string }
export interface Message { id: string; text: string; mine: boolean; time: string }
export interface Conversation { id: string; side: Role; name: string; company: string; role: string; messages: Message[] }
export interface TeamMember { id: string; name: string; email: string; role: 'Owner' | 'Hiring manager' | 'Recruiter' | 'Interviewer' }

export interface DemoState {
  profile: CandidateProfile
  organization: Organization
  opportunities: Opportunity[]
  vacancies: Vacancy[]
  candidates: CandidateProfile[]
  decisions: Record<string, Decision>
  candidateDecisions: Record<string, Decision>
  matches: MutualMatch[]
  pipeline: PipelineEntry[]
  interviews: Interview[]
  offers: Offer[]
  policy: PactPolicy
  consents: ConsentRecord[]
  evidence: VerificationSummary[]
  clarifications: ClarificationRequest[]
  notifications: Notification[]
  conversations: Conversation[]
  team: TeamMember[]
  preferences: { email: boolean; digest: boolean; quietHours: boolean }
  revision: number
}

export type ApiErrorCode = 'unauthorized' | 'forbidden' | 'conflict' | 'offline' | 'expired' | 'unknown'
export class ApiError extends Error {
  constructor(public code: ApiErrorCode, message: string) { super(message) }
}
export interface FrontendAdapter {
  getState(): Promise<DemoState>
  update(updater: (current: DemoState) => DemoState, expectedRevision: number): Promise<DemoState>
  reset(): Promise<DemoState>
}

/* ---------- The Pass (employer-side matching) ---------- */
/** How a fact is known. `confirmed` = attested or stated by the person; `inferred` = derived from profile signals; `unknown` = not yet known. */
export type Provenance = 'confirmed' | 'inferred' | 'unknown'
export type RecipeWeight = 'must' | 'nice' | 'off'
export type Arrangement = 'Hybrid · NYC 2 days' | 'Remote (US)'
export interface RecipeItem { id: string; label: string; weight: RecipeWeight }
export interface PassOrder {
  id: string
  vacancyId: string
  ticket: string
  title: string
  company: string
  recipe: RecipeItem[]
  arrangement: Arrangement
  /** Salary ceiling in thousands of USD. */
  ceiling: number
  /** Taste tests (verification requests) available for this order. */
  verificationBudget: number
}
export interface Signal { status: Provenance; meets: boolean; note: string; evidence?: string }
export interface PassCandidate {
  id: string
  ticket: string
  name: string
  title: string
  location: string
  years: number
  summary: string
  /** Position suggested by global allocation for this round. Advisory only. */
  allocationRank: number
  signals: Record<string, Signal>
  arrangement: { value: 'Remote only' | 'Hybrid' | 'Either'; status: Provenance }
  /** Compensation floor in thousands of USD, null when unknown. */
  floor: { value: number | null; status: Provenance }
  priorities: string[]
  questions: string[]
  evidence: { label: string; issuer: string; status: 'Verified' | 'Self-reported' }[]
}
export interface TasteTest {
  id: string
  candidateId: string
  topic: string
  /** Recipe item id, or 'floor' / 'arrangement'. */
  subject: string
  question: string
  status: 'Awaiting reply' | 'Answered'
  answer?: string
  sent: string
}
export interface PassState {
  order: PassOrder
  candidates: PassCandidate[]
  tasteTests: TasteTest[]
  /** Candidate ids the employer chose to bring to the pass beyond the service limit. */
  pinned: string[]
  introductions: Record<string, 'Requested' | 'Passed'>
  log: { id: string; text: string; time: string }[]
}
