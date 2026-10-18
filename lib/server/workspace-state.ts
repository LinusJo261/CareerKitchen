import 'server-only'
import type {
  Role,
  Stage,
  Vacancy,
  Opportunity,
  CandidateProfile,
} from '../contracts'
import {
  emptyWorkspace,
  type ApiSchema,
  type WorkspaceState,
} from '../workspace-types'
import { Backend } from './backend'
import { currentClaim, currentTerms, currentDisclosure } from './consent-view'

const human = (value: string) =>
  value
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/^./, (x) => x.toUpperCase())
const date = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
      })
    : 'Not set'
const money = (
  min: string | number,
  max: string | number,
  currency: string,
  period: string,
) =>
  `${new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(min))} – ${new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(max))} / ${human(period)}`
const stage = (value: string): Stage =>
  value === 'START_CONFIRMED'
    ? 'Employment confirmed'
    : ['OFFERED', 'OFFER_ACCEPTED', 'START_REPORTED'].includes(value)
      ? 'Offer'
      : value === 'INTERVIEWING'
        ? 'Interviewing'
        : 'Mutual interest'
const decodeText = (value: string) =>
  value
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&#x27;', "'")
    .replaceAll('&quot;', '"')
    .replaceAll('&amp;', '&')
function vacancyView(
  row: ApiSchema['VacancyOut'],
  organizations: ApiSchema['OrganizationOut'][],
  sample = false,
): Vacancy {
  const org = organizations.find((x) => x.id === row.org_id)
  return {
    id: row.id,
    version: row.version,
    orgId: row.org_id,
    termsHash: row.terms_hash,
    title: row.title,
    company: row.organization_name || org?.display_name || 'Employer',
    salary:
      sample && Number(row.pay_min) === 0 && Number(row.pay_max) === 0
        ? 'Compensation not specified'
        : money(
            row.pay_min,
            row.pay_max,
            row.currency,
            row.compensation_period,
          ),
    location: row.location_region || 'Remote',
    arrangement: human(row.work_mode),
    skills: row.requirements.map((x) => (sample ? x.key : x.description)),
    summary: row.description,
    deadline: date(row.deadline_at),
    verified: org?.verification_state === 'VERIFIED',
    employerInterested: false,
    status:
      row.state === 'ACTIVE'
        ? 'Active'
        : row.state === 'DRAFT'
          ? 'Draft'
          : 'Closed',
    employmentType: human(row.employment_type),
    required: row.requirements
      .filter((x) => x.kind === 'ESSENTIAL')
      .map((x) => x.description),
    preferred: row.requirements
      .filter((x) => x.kind === 'PREFERENCE')
      .map((x) => (sample ? x.key : x.description)),
    startWindow: `${date(row.start_from)} – ${date(row.start_until)}`,
  }
}

export async function workspaceState(
  api: Backend,
  role: Role,
  mode: WorkspaceState['context']['mode'],
): Promise<WorkspaceState> {
  const state = emptyWorkspace(role),
    b = state.backend
  let candidateHistory: ApiSchema['PairHistoryOut'][] = []
  let candidateWaiting: ApiSchema['WaitingOut'][] = []
  state.session = await api.get<ApiSchema['IdentityOut']>('/v1/sessions/me')
  state.context.mode = mode
  if (mode === 'sample') {
    state.context.sampleDemo =
      await api.get<NonNullable<WorkspaceState['context']['sampleDemo']>>(
        '/v1/demo/status',
      )
  }
  const [candidate, allOrgs, notificationPrefs, notifications, privacyExport] =
    await Promise.all([
      api.optional<ApiSchema['CandidateOut'] | null>(
        '/v1/candidates/me',
        null,
        [404],
      ),
      api.get<ApiSchema['OrganizationOut'][]>('/v1/organizations'),
      api.get<ApiSchema['NotificationPreferencesOut']>(
        '/v1/notifications/preferences',
      ),
      api.all<ApiSchema['NotificationOut']>('/v1/notifications'),
      api.optional<ApiSchema['ExportOut'] | null>(
        '/v1/privacy/export',
        null,
        [404],
      ),
    ])
  // The full sample catalogue is paginated separately. Keep the interactive
  // employer workspace focused on the vacancies used by the live demonstration.
  const orgs =
    mode === 'sample'
      ? allOrgs.filter(
          (org) => org.id === state.context.sampleDemo?.organization_id,
        )
      : allOrgs
  b.candidate = candidate
  b.organizations = orgs
  b.notificationPreferences = notificationPrefs
  b.notifications = notifications
  b.privacyExport = privacyExport
  b.memberships = state.session.memberships
  state.context.organizationId = orgs[0]?.id || null
  if (role === 'employer') {
    const vacancies = await Promise.all(
      orgs.map((org) =>
        api.optional<ApiSchema['VacancyOut'][]>(
          `/v1/organizations/${org.id}/vacancies`,
          [],
          [403],
        ),
      ),
    )
    b.vacancies = vacancies
      .flat()
      .filter(
        (vacancy) =>
          mode !== 'sample' ||
          state.context.sampleDemo?.vacancy_ids.includes(vacancy.id),
      )
    const policies = await Promise.all(
      orgs.map((org) =>
        api.optional<ApiSchema['PolicyOut'][]>(
          `/v1/organizations/${org.id}/pact/policies`,
          [],
          [403],
        ),
      ),
    )
    b.policies = policies.flat()
    const perVacancy = await Promise.all(
      b.vacancies.map(async (vacancy) => {
        const [inbox, matches, clarifications, shortlist] = await Promise.all([
          api
            .request<ApiSchema['DecisionCardOut'][]>(
              `/v1/vacancies/${vacancy.id}/decisions`,
            )
            .catch((error) => {
              if (error.status === 403)
                return {
                  data: [],
                  capacity: { used: 0, maximum: vacancy.cap },
                }
              throw error
            }),
          api.optional<ApiSchema['MatchOut'][]>(
            `/v1/vacancies/${vacancy.id}/pipeline`,
            [],
            [403],
          ),
          api.optional<ApiSchema['ClarificationOut'][]>(
            `/v1/vacancies/${vacancy.id}/pact/clarifications`,
            [],
            [403],
          ),
          api.optional<ApiSchema['ShortlistOut'] | null>(
            `/v1/vacancies/${vacancy.id}/shortlist/status`,
            null,
            [403],
          ),
        ])
        if (inbox.capacity) b.capacities[vacancy.id] = inbox.capacity
        if (shortlist) b.shortlist[vacancy.id] = shortlist
        return { decisions: inbox.data, matches, clarifications }
      }),
    )
    b.employerDecisions = perVacancy.flatMap((x) => x.decisions)
    b.matches = perVacancy.flatMap((x) => x.matches)
    b.clarifications = perVacancy.flatMap((x) => x.clarifications)
    const org = orgs[0]
    b.memberships = (
      await Promise.all(
        orgs.map((item) =>
          api.optional<ApiSchema['MemberOut'][]>(
            `/v1/organizations/${item.id}/members`,
            state.session!.memberships.filter((x) => x.org_id === item.id),
            [403],
          ),
        ),
      )
    ).flat()
  } else if (candidate) {
    const [
      inbox,
      matches,
      skills,
      claims,
      consents,
      policies,
      history,
      waiting,
    ] = await Promise.all([
      api.request<ApiSchema['DecisionCardOut'][]>(
        '/v1/candidates/me/decisions',
      ),
      api.get<ApiSchema['MatchOut'][]>('/v1/candidates/me/matches'),
      api.get<ApiSchema['SkillOut'][]>('/v1/candidates/me/skills'),
      api.get<ApiSchema['ClaimOut'][]>('/v1/evidence/claims/me'),
      api.get<ApiSchema['ConsentLedgerOut']>('/v1/consents/me'),
      api.get<ApiSchema['PolicyOut'][]>('/v1/candidates/me/pact/policies'),
      api.all<ApiSchema['PairHistoryOut']>('/v1/candidates/me/history'),
      api.get<ApiSchema['WaitingOut'][]>('/v1/candidates/me/waiting'),
    ])
    candidateHistory = history
    candidateWaiting = waiting
    b.candidateDecisions = inbox.data
    b.capacities[candidate.id] = inbox.capacity || {
      used: inbox.data.length,
      maximum: candidate.cap,
    }
    b.matches = matches
    b.skills = skills
    b.evidence = claims
    b.consents = consents
    b.policies = policies
    const known = new Map(inbox.data.map((x) => [x.vacancy.id, x.vacancy]))
    const roleIds = new Set([
      ...matches.map((x) => x.vacancy.id),
      ...waiting.flatMap((x) => (x.vacancy_id ? [x.vacancy_id] : [])),
      ...history
        .filter((x) => x.state === 'CLOSED_PASSED')
        .map((x) => x.vacancy_id),
    ])
    const missing = await Promise.all(
      [...roleIds]
        .filter((id) => !known.has(id))
        .map((id) =>
          api.optional<ApiSchema['VacancyOut'] | null>(
            `/v1/vacancies/${id}`,
            null,
            [403, 404],
          ),
        ),
    )
    missing.forEach((x) => {
      if (x) known.set(x.id, x)
    })
    b.vacancies = [...known.values()]
  }
  state.vacancies = b.vacancies.map((x) =>
    vacancyView(x, orgs, mode === 'sample'),
  )
  if (candidate)
    state.profile = {
      id: candidate.id,
      version: candidate.version,
      state: candidate.state,
      name: mode === 'sample' ? 'Sample applicant' : state.session.email,
      title: candidate.headline,
      summary: candidate.summary,
      location: candidate.region,
      skills: b.skills.map((x) => x.name),
      capacity: candidate.cap,
      availability: candidate.available_from
        ? date(candidate.available_from)
        : 'Not set',
      experience: candidate.experiences?.length
        ? `${candidate.experiences.length} experience entries`
        : 'Not set',
      compensation:
        candidate.compensation_floor == null
          ? 'Not set'
          : `${candidate.compensation_floor} ${candidate.currency} / ${human(candidate.compensation_period)}`,
      remote: candidate.work_modes.map(human).join(' or '),
      privacy: true,
      roles: candidate.role_families,
    }
  const org = orgs[0]
  if (org)
    state.organization = {
      id: org.id,
      version: org.version,
      name: org.display_name,
      verified: org.verification_state === 'VERIFIED',
      verification:
        org.verification_state === 'VERIFIED' ? 'Verified' : 'Pending',
      description: org.legal_name,
      domain: org.domain,
    }
  state.opportunities = b.candidateDecisions.map((card) => ({
    ...vacancyView(card.vacancy, orgs, mode === 'sample'),
    decisionId: card.id,
    cycleVersion: card.cycle_version,
    decisionToken: card.decision_token,
    deadline: date(card.expires_at),
    employerInterested: card.other_side_interested,
    reason: card.reason_codes.length
      ? card.reason_codes.map(human).join(' · ')
      : 'Selected by the backend from your current preferences.',
  })) as Opportunity[]
  const currentRoles = new Set(state.opportunities.map((x) => x.id))
  for (const waiting of candidateWaiting) {
    const vacancy = b.vacancies.find((x) => x.id === waiting.vacancy_id)
    if (vacancy && !currentRoles.has(vacancy.id)) {
      state.opportunities.push({
        ...vacancyView(vacancy, orgs, mode === 'sample'),
        reason:
          'Your interest is recorded. Awaiting the employer’s separate decision.',
      })
      state.decisions[vacancy.id] = 'interested'
      currentRoles.add(vacancy.id)
    }
  }
  for (const previous of candidateHistory) {
    const vacancy = b.vacancies.find((x) => x.id === previous.vacancy_id)
    if (
      previous.state === 'CLOSED_PASSED' &&
      vacancy &&
      !currentRoles.has(vacancy.id)
    ) {
      state.opportunities.push({
        ...vacancyView(vacancy, orgs, mode === 'sample'),
        reason: 'This introduction was passed. Your response is recorded.',
      })
      state.decisions[vacancy.id] = 'passed'
      currentRoles.add(vacancy.id)
    }
  }
  state.candidates = b.employerDecisions
    .filter((x) => x.candidate)
    .map((card) => ({
      id: card.candidate!.id,
      version: card.version,
      decisionId: card.id,
      vacancyId: card.vacancy.id,
      cycleVersion: card.cycle_version,
      decisionToken: card.decision_token,
      name: card.candidate!.headline,
      title: card.candidate!.headline,
      summary: card.candidate!.summary,
      location: card.candidate!.region,
      skills: card.candidate!.skills,
      capacity: 0,
      availability: 'Not disclosed',
      experience: card.candidate!.experiences?.length
        ? `${card.candidate!.experiences.length} entries`
        : 'Not disclosed',
      compensation: 'Private',
      remote: human(card.vacancy.work_mode),
      privacy: true,
    })) as CandidateProfile[]
  state.matches = b.matches.map((row) => ({
    id: row.id,
    version: row.version,
    cycleVersion: row.cycle_version,
    state: row.state,
    status: row.status,
    vacancyId: row.vacancy.id,
    orgId: row.vacancy.org_id,
    startReport: row.start_report,
    candidateId: row.candidate.id,
    opportunityId: row.vacancy.id,
    name: row.candidate.headline,
    role: row.vacancy.title,
    company:
      row.vacancy.organization_name ||
      orgs.find((x) => x.id === row.vacancy.org_id)?.display_name ||
      'Employer',
    stage: stage(row.state),
    updated: row.timeline.at(-1)
      ? date(row.timeline.at(-1)!.occurred_at)
      : 'Current',
  }))
  state.pipeline = state.matches.map((row) => ({
    id: row.id,
    matchId: row.id,
    version: row.version,
    cycleVersion: row.cycleVersion,
    vacancyId: row.vacancyId,
    state: row.state,
    name: row.name,
    title: row.role,
    vacancy: row.role,
    stage: row.stage,
    interest: 'Mutual',
    updated: row.updated,
    verifiedEvidence: 0,
    skills: [],
  }))
  state.offers = b.matches.flatMap((match) =>
    match.offers.map((offer) => ({
      id: offer.id,
      version: offer.version || 1,
      matchId: match.id,
      cycleVersion: match.cycle_version,
      company: match.vacancy.organization_name || 'Employer',
      role: match.vacancy.title,
      salary: 'See written offer terms below',
      terms: decodeText(offer.terms),
      deadline: date(offer.expires_at),
      expiresAt: offer.expires_at,
      start: date(offer.start_at),
      startsAt: offer.start_at,
      status:
        offer.status === 'ACCEPTED'
          ? ('Accepted' as const)
          : offer.status === 'DECLINED'
            ? ('Declined' as const)
            : ('Awaiting response' as const),
      backendStatus: offer.status,
    })),
  )
  const activeMatches = b.matches.filter(
    (x) =>
      x.status === 'ACTIVE' &&
      [
        'MUTUAL_MATCH',
        'INTERVIEWING',
        'OFFERED',
        'OFFER_ACCEPTED',
        'START_REPORTED',
        'START_CONFIRMED',
      ].includes(x.state),
  )
  const conversations = await Promise.all(
    activeMatches.map(async (match) => {
      const [messages, proposals] = await Promise.all([
        api.all<ApiSchema['MessageOut']>(`/v1/matches/${match.id}/messages`),
        api.get<ApiSchema['InterviewProposalOut'][]>(
          `/v1/matches/${match.id}/interviews/proposals`,
        ),
      ])
      b.proposals.push(...proposals.map((x) => ({ ...x, match_id: match.id })))
      return {
        id: match.id,
        matchId: match.id,
        version: match.version,
        side: role,
        name:
          role === 'candidate'
            ? match.vacancy.organization_name || 'Employer'
            : match.candidate.headline,
        company: match.vacancy.organization_name || 'Employer',
        role: match.vacancy.title,
        messages: messages.map((x) => ({
          id: x.id,
          text: decodeText(x.body),
          mine: x.sender_user_id === state.session!.id,
          time: new Date(x.created_at).toLocaleTimeString('en-US', {
            hour: 'numeric',
            minute: '2-digit',
          }),
        })),
      }
    }),
  )
  state.conversations = conversations
  state.interviews = b.matches.flatMap((match) =>
    match.interviews.map((row) => ({
      id: row.id,
      matchId: match.id,
      side: role,
      company: match.vacancy.organization_name || 'Employer',
      role: match.vacancy.title,
      person: role === 'candidate' ? 'Employer' : match.candidate.headline,
      date: row.start_at.slice(0, 10),
      time: new Date(row.start_at).toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
      }),
      format: 'Interview',
      status: 'Confirmed' as const,
      startAt: row.start_at,
      endAt: row.end_at,
    })),
  )
  state.interviews.push(
    ...b.proposals
      .filter((x) => x.status === 'PROPOSED')
      .map((row) => {
        const match = b.matches.find((x) => x.id === row.match_id)!
        return {
          id: row.id,
          matchId: row.match_id,
          proposalId: row.id,
          version: row.version,
          initiatorId: row.initiator_id || undefined,
          canConfirm: row.can_confirm ?? undefined,
          slots: row.slots,
          timezoneLabel: row.timezone_label,
          proposalStatus: row.status,
          side: role,
          company: match.vacancy.organization_name || 'Employer',
          role: match.vacancy.title,
          person: match.candidate.headline,
          date: row.slots[0]?.start_at.slice(0, 10) || '',
          time: 'Choose a proposed slot',
          format: 'Proposed interview',
          status: 'Scheduled' as const,
        }
      }),
  )
  state.evidence = b.evidence.map((row) => ({
    id: row.id,
    version: row.version,
    name: `${human(row.claim_type)} · ${row.requirement_keys.join(', ')}`,
    status: currentClaim(row)
      ? 'Verified'
      : row.status === 'PENDING'
        ? 'Pending'
        : 'Not shared',
    backendStatus:
      row.status === 'VERIFIED' && !currentClaim(row) ? 'EXPIRED' : row.status,
    issuer:
      row.status === 'VERIFIED'
        ? 'Independent verification recorded'
        : human(row.status),
    requirementKeys: row.requirement_keys,
    expiresAt: row.expires_at,
  }))
  state.consents = [
    ...b.consents.terms.map((row) => ({
      id: row.id,
      version: row.version,
      vacancyId: row.vacancy_id,
      scope: row.scope,
      label: human(row.scope),
      recipient:
        state.vacancies.find((v) => v.id === row.vacancy_id)?.company ||
        'Exact employer',
      purpose: `Terms for vacancy ${row.vacancy_id}, version ${row.role_version}`,
      expires: date(row.expires_at),
      expiresAt: row.expires_at,
      granted: currentTerms(
        row,
        b.vacancies.find((v) => v.id === row.vacancy_id),
      ),
    })),
    ...b.consents.evidence.map((row) => ({
      id: row.id,
      version: row.version,
      vacancyId: row.vacancy_id,
      orgId: row.org_id,
      claimId: row.claim_id,
      kind: row.kind,
      label: human(row.kind),
      recipient:
        state.vacancies.find((v) => v.id === row.vacancy_id)?.company ||
        'Exact employer',
      purpose: `Claim ${row.claim_id} for vacancy ${row.vacancy_id}, version ${row.role_version}`,
      expires: date(row.expires_at),
      expiresAt: row.expires_at,
      granted: currentDisclosure(
        row,
        b.vacancies.find((v) => v.id === row.vacancy_id),
        b.evidence.find((c) => c.id === row.claim_id),
      ),
    })),
  ]
  const policy = b.policies[0]
  if (policy) {
    const vacancyId = Object.keys(policy.scope)[0],
      v = state.vacancies.find((x) => x.id === vacancyId),
      consent = b.consents.terms.find(
        (x) =>
          x.vacancy_id === vacancyId &&
          !x.revoked_at &&
          new Date(x.expires_at) > new Date(),
      )
    state.policy = {
      id: policy.id,
      resourceVersion: policy.version,
      version: `v${policy.version}`,
      vacancyId,
      scopeHash: policy.scope_hash,
      stage: policy.stage,
      role: v?.title || 'Exact role',
      compensation: v?.salary || 'See role terms',
      arrangement: v?.arrangement || 'See role terms',
      requirements: v?.required || [],
      evidence: [],
      stages: [human(policy.stage)],
      authority: 'Authorized signatory required',
      expires: date(policy.expires_at),
      expiresAt: policy.expires_at,
      revocation: 'You can revoke consent at any time.',
      status:
        policy.state === 'AUTHORIZED'
          ? 'Authorized'
          : policy.state === 'REVOKED'
            ? 'Revoked'
            : 'Draft',
      candidateConfirmed: Boolean(consent),
      consentId: consent?.id,
      consentVersion: consent?.version,
    }
  }
  state.team = b.memberships.map((row) => ({
    id: row.id,
    version: row.version || 1,
    userId: row.user_id || undefined,
    name:
      row.user_id === state.session!.id
        ? 'You'
        : `Member ${row.user_id?.slice(0, 8) || row.id.slice(0, 8)}`,
    email: row.user_id === state.session!.id ? state.session!.email : 'Private',
    role:
      row.role === 'ORG_ADMIN'
        ? 'Owner'
        : row.role === 'HIRING_MANAGER'
          ? 'Hiring manager'
          : 'Recruiter',
    backendRole: row.role,
    status: row.status || 'ACTIVE',
  }))
  state.notifications = notifications.map((row) => ({
    id: row.id,
    version: row.version,
    side: role,
    title: human(row.kind),
    description: `Recorded ${date(row.created_at)}`,
    read: Boolean(row.read_at),
    href: row.kind.startsWith('message.')
      ? `/${role}/messages`
      : row.kind.startsWith('interview.')
        ? `/${role}/interviews`
        : row.kind.startsWith('offer.')
          ? `/${role}/offers`
          : undefined,
  }))
  state.preferences = {
    email: notificationPrefs.email_opt_in,
    digest: false,
    inApp: notificationPrefs.in_app_opt_in,
    quietHours: Object.keys(notificationPrefs.quiet_hours || {}).length > 0,
    quiet_hours: notificationPrefs.quiet_hours,
    version: notificationPrefs.version,
  }
  if (privacyExport) state.privacyJobs = [{ ...privacyExport, kind: 'EXPORT' }]
  return state
}
