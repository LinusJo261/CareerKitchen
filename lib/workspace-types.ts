import type { components } from "../packages/api-client/src/schema";
import type { DemoState, Role } from "./contracts";

export type ApiSchema = components["schemas"];
export interface WorkspaceBackend {
  candidate: ApiSchema["CandidateOut"] | null;
  skills: ApiSchema["SkillOut"][];
  organizations: ApiSchema["OrganizationOut"][];
  vacancies: ApiSchema["VacancyOut"][];
  candidateDecisions: ApiSchema["DecisionCardOut"][];
  employerDecisions: ApiSchema["DecisionCardOut"][];
  matches: ApiSchema["MatchOut"][];
  policies: ApiSchema["PolicyOut"][];
  clarifications: ApiSchema["ClarificationOut"][];
  memberships: ApiSchema["MemberOut"][];
  capacities: Record<string, ApiSchema["Capacity"]>;
  shortlist: Record<string, ApiSchema["ShortlistOut"]>;
  proposals: (ApiSchema["InterviewProposalOut"] & { match_id: string })[];
  evidence: ApiSchema["ClaimOut"][];
  consents: ApiSchema["ConsentLedgerOut"];
  notifications: ApiSchema["NotificationOut"][];
  notificationPreferences: ApiSchema["NotificationPreferencesOut"];
  privacyExport: ApiSchema["ExportOut"] | null;
  lastInvitation?: ApiSchema["InvitationOut"] & { org_id: string };
}
export interface WorkspaceState extends DemoState {
  session: ApiSchema["IdentityOut"] | null;
  context: {
    mode: "local" | "supabase" | "unconfigured";
    role: Role;
    organizationId: string | null;
  };
  backend: WorkspaceBackend;
  privacyJobs: {
    operation_id: string;
    status: string;
    kind?: string;
    export?: unknown;
  }[];
  warnings: string[];
}

export function emptyWorkspace(role: Role = "candidate"): WorkspaceState {
  return {
    revision: 0,
    session: null,
    context: { mode: "unconfigured", role, organizationId: null },
    profile: {
      id: "",
      version: 0,
      name: "Your profile",
      title: "",
      location: "",
      skills: [],
      summary: "",
      capacity: 3,
      availability: "Not set",
      experience: "Not set",
      compensation: "Not set",
      remote: "Remote",
      privacy: true,
    },
    organization: {
      id: "",
      name: "Your organization",
      verified: false,
      description: "",
      verification: "Not started",
    },
    opportunities: [],
    vacancies: [],
    candidates: [],
    decisions: {},
    candidateDecisions: {},
    matches: [],
    pipeline: [],
    interviews: [],
    offers: [],
    policy: {
      id: "",
      role: "",
      version: "",
      compensation: "",
      arrangement: "",
      requirements: [],
      evidence: [],
      stages: [],
      authority: "",
      expires: "",
      revocation: "Revocable",
      status: "Draft",
      candidateConfirmed: false,
    },
    consents: [],
    evidence: [],
    clarifications: [],
    notifications: [],
    conversations: [],
    team: [],
    preferences: {
      email: false,
      digest: false,
      quietHours: false,
      inApp: true,
      version: 1,
      quiet_hours: {},
    },
    backend: {
      candidate: null,
      skills: [],
      organizations: [],
      vacancies: [],
      candidateDecisions: [],
      employerDecisions: [],
      matches: [],
      policies: [],
      clarifications: [],
      memberships: [],
      capacities: {},
      shortlist: {},
      proposals: [],
      evidence: [],
      consents: { terms: [], evidence: [] },
      notifications: [],
      notificationPreferences: {
        version: 1,
        email_opt_in: false,
        in_app_opt_in: true,
        quiet_hours: {},
      },
      privacyExport: null,
    },
    privacyJobs: [],
    warnings: [],
  };
}
