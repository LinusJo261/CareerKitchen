import 'server-only'
import type { ApiSchema } from '../workspace-types'
import { Backend } from './backend'
import { GatewayError } from './http-utils'

type Payload = Record<string, unknown>
const id = (value: unknown) => {
  if (
    typeof value !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      value,
    )
  )
    throw new GatewayError(
      422,
      'INVALID_ID',
      'Choose a current resource before continuing.',
    )
  return value
}
const version = (p: Payload, key = 'expected_version') => {
  const value = p[key]
  if (!Number.isInteger(value) || Number(value) < 0)
    throw new GatewayError(
      422,
      'VERSION_REQUIRED',
      'Refresh this page and review the current resource version.',
    )
  return value as number
}
const pick = (p: Payload, keys: string[]) =>
  Object.fromEntries(
    keys.filter((k) => p[k] !== undefined).map((k) => [k, p[k]]),
  )
const vacancyFields = [
  'org_id',
  'title',
  'description',
  'role_family',
  'employment_type',
  'work_mode',
  'location_region',
  'pay_min',
  'pay_max',
  'currency',
  'compensation_period',
  'openings_total',
  'cap',
  'deadline_at',
  'start_from',
  'start_until',
]
const candidateFields = [
  'display_name',
  'professional_links',
  'headline',
  'summary',
  'region',
  'role_families',
  'employment_types',
  'work_modes',
  'locations',
  'compensation_floor',
  'currency',
  'compensation_period',
  'experiences',
  'education',
  'cap',
  'available_from',
  'available_until',
  'terms_accepted',
  'privacy_accepted',
  'profile_confirmed',
]

export async function workspaceCommand(
  api: Backend,
  action: string,
  p: Payload,
  key: string,
): Promise<unknown> {
  const change = async (path: string, body?: unknown, method = 'POST') =>
    (await api.request(path, { method, body, key })).data
  switch (action) {
    case 'demo.reconcile': {
      if (api.mode !== 'sample')
        throw new GatewayError(
          403,
          'DEMO_ONLY',
          'Enter demo mode to run sample matching.',
        )
      return change('/v1/demo/reconcile', {})
    }
    case 'candidate.save': {
      if (p.patch && typeof p.patch === 'object') {
        if (!p.profile || typeof p.profile !== 'object')
          throw new GatewayError(
            422,
            'PROFILE_REQUIRED',
            'Refresh the profile before saving changes.',
          )
        const current = p.profile as Payload
        const patch = p.patch as Payload
        const updates = {
          ...patch,
          ...(patch.title !== undefined ? { headline: patch.title } : {}),
          ...(patch.location !== undefined ? { region: patch.location } : {}),
          ...(patch.capacity !== undefined ? { cap: patch.capacity } : {}),
        }
        return change(
          '/v1/candidates/me',
          {
            ...pick(current, candidateFields),
            ...pick(updates, candidateFields),
            expected_version: version(p),
            profile_confirmed: true,
          },
          'PUT',
        )
      }
      return change(
        '/v1/candidates/me',
        { ...pick(p, candidateFields), expected_version: version(p) },
        'PUT',
      )
    }
    case 'candidate.preferences': {
      return change(
        '/v1/candidates/me/preferences',
        {
          ...pick(p, [
            'compensation_floor',
            'currency',
            'compensation_period',
            'employment_types',
            'work_modes',
            'locations',
          ]),
          cap: p.capacity ?? p.cap,
          expected_version: version(p),
        },
        'PUT',
      )
    }
    case 'candidate.activate':
    case 'candidate.pause':
      return change(
        `/v1/candidates/me/${action.endsWith('activate') ? 'activate' : 'pause'}`,
        { expected_version: version(p) },
      )
    case 'candidate.skill.add':
      return change('/v1/candidates/me/skills', {
        name: p.name,
        level: p.level ?? 3,
      })
    case 'candidate.skill.remove': {
      const skills = await api.get<ApiSchema['SkillOut'][]>(
        '/v1/candidates/me/skills',
      )
      const skill = skills.find((x) => x.id === p.id || x.name === p.name)
      if (!skill)
        throw new GatewayError(
          404,
          'SKILL_NOT_FOUND',
          'This skill is no longer in your profile.',
        )
      return change(
        `/v1/candidates/me/skills/${skill.id}`,
        { expected_version: p.expected_version ?? skill.version },
        'DELETE',
      )
    }
    case 'decision.answer': {
      if (typeof p.interested !== 'boolean')
        throw new GatewayError(
          422,
          'INVALID_DECISION',
          'Choose Interested or Pass explicitly.',
        )
      return change(
        `/v1/decisions/${id(p.id)}/${p.interested ? 'interested' : 'pass'}`,
        {
          expected_cycle_version: p.expected_cycle_version ?? p.cycleVersion,
          decision_token: p.decision_token ?? p.decisionToken,
        },
      )
    }
    case 'offer.answer': {
      if (p.status !== 'Accepted' && p.status !== 'Declined')
        throw new GatewayError(
          422,
          'INVALID_DECISION',
          'Choose Accept or Decline explicitly.',
        )
      return change(
        `/v1/offers/${id(p.id)}/${p.status === 'Accepted' ? 'accept' : 'decline'}`,
        { expected_version: version(p) },
      )
    }
    case 'offer.create':
      return change(`/v1/matches/${id(p.matchId)}/offers`, {
        ...pick(p, [
          'terms',
          'expires_at',
          'start_at',
          'affirm_human_authority',
        ]),
        expected_version: version(p),
      })
    case 'start.report':
      return change(`/v1/matches/${id(p.matchId)}/starts/report`, {
        expected_version: version(p),
        started_at: p.started_at ?? p.start_at,
        source_reference: p.source_reference ?? p.evidence_reference,
      })
    case 'message.send':
      return change(`/v1/matches/${id(p.matchId)}/messages`, {
        expected_version: version(p),
        body: p.body,
        ...(p.attachment_id ? { attachment_id: p.attachment_id } : {}),
      })
    case 'interview.propose':
      return change(`/v1/matches/${id(p.matchId)}/interviews/proposals`, {
        expected_version: version(p),
        slots: p.slots,
        timezone_label: p.timezone_label,
      })
    case 'interview.confirm':
      return change(
        `/v1/matches/${id(p.matchId)}/interviews/${id(p.id)}/confirm`,
        { expected_version: version(p), slot_index: p.slot_index },
      )
    case 'stage.update':
      return change(`/v1/matches/${id(p.matchId)}/stages`, {
        expected_version: version(p),
        stage: p.stage,
        source_reference: p.source_reference,
      })
    case 'notification.read':
      return change(`/v1/notifications/${id(p.id)}/read`, {
        expected_version: version(p),
      })
    case 'notifications.preferences':
      return change(
        '/v1/notifications/preferences',
        {
          expected_version: version(p),
          ...pick(p, ['email_opt_in', 'in_app_opt_in', 'quiet_hours']),
        },
        'PUT',
      )
    case 'privacy.export':
      return change('/v1/privacy/export')
    case 'privacy.export.status':
      return api.get('/v1/privacy/export')
    case 'privacy.delete':
      return change('/v1/privacy/delete')
    case 'organization.create':
      return change(
        '/v1/organizations',
        pick(p, ['legal_name', 'display_name', 'domain']),
      )
    case 'organization.save':
      return change(
        `/v1/organizations/${id(p.id)}`,
        { expected_version: version(p), display_name: p.display_name },
        'PATCH',
      )
    case 'team.invite':
      return change(
        `/v1/organizations/${id(p.orgId)}/members/invite`,
        pick(p, ['email', 'role']),
      )
    case 'team.accept':
      return change('/v1/organizations/invitations/accept', { token: p.token })
    case 'team.update':
      return change(
        `/v1/organizations/${id(p.orgId)}/members/${id(p.id)}`,
        { expected_version: version(p), role: p.role },
        'PATCH',
      )
    case 'team.revoke':
      return change(
        `/v1/organizations/${id(p.orgId)}/members/${id(p.id)}`,
        { expected_version: version(p) },
        'DELETE',
      )
    case 'vacancy.create':
      return change('/v1/vacancies', pick(p, vacancyFields))
    case 'vacancy.save':
      return change(
        `/v1/vacancies/${id(p.id)}`,
        { ...pick(p, vacancyFields), expected_version: version(p) },
        'PATCH',
      )
    case 'vacancy.activate':
    case 'vacancy.pause':
    case 'vacancy.close':
      return change(`/v1/vacancies/${id(p.id)}/${action.split('.')[1]}`, {
        expected_version: version(p),
      })
    case 'requirement.create':
      return change(`/v1/vacancies/${id(p.vacancyId)}/requirements`, {
        expected_version: version(p),
        ...pick(p, [
          'key',
          'description',
          'kind',
          'lawful_reason',
          'human_reviewed',
        ]),
      })
    case 'policy.create':
      return change('/v1/pact/policies', {
        roles: [
          {
            vacancy_id: id(p.vacancyId),
            expected_version: version(p),
            terms_hash: p.terms_hash,
          },
        ],
        ...pick(p, ['policy_text', 'stage', 'expires_at']),
      })
    case 'policy.authorize':
      return change(`/v1/pact/policies/${id(p.id)}/authorize`, {
        expected_version: version(p),
        scope_hash: p.scope_hash,
        affirm_human_authority: p.affirm_human_authority,
      })
    case 'policy.revoke':
      return change(`/v1/pact/policies/${id(p.id)}/revoke`, {
        expected_version: version(p),
        ...(p.reason ? { reason: p.reason } : {}),
      })
    case 'policy.load':
      return api.get(`/v1/pact/policies/${id(p.id)}`)
    case 'clarification.create': {
      const v = await api.get<ApiSchema['VacancyOut']>(
        `/v1/vacancies/${id(p.vacancyId)}`,
      )
      const r = v.requirements.find((x) => x.id === p.requirementId)
      if (!r)
        throw new GatewayError(
          404,
          'REQUIREMENT_NOT_FOUND',
          'Refresh the role requirements.',
        )
      return change('/v1/pact/clarifications', {
        vacancy_id: v.id,
        expected_version: version(p),
        terms_hash: p.terms_hash ?? v.terms_hash,
        requirement_id: r.id,
        requirement_expected_version:
          p.requirement_expected_version ?? r.version,
        proposed_kind: 'PREFERENCE',
        ...pick(p, ['proposed_text', 'reason', 'expires_at']),
      })
    }
    case 'clarification.respond':
      return change(`/v1/pact/clarifications/${id(p.id)}/respond`, {
        expected_version: version(p),
        vacancy_id: p.vacancy_id ?? p.vacancyId,
        role_version: p.role_version,
        requirement_id: p.requirement_id ?? p.requirementId,
        approved: p.approved,
        affirm_human_authority: p.affirm_human_authority,
      })
    case 'research.replan':
      return change(`/v1/vacancies/${id(p.vacancyId)}/shortlist/replan`, {
        expected_version: version(p),
      })
    case 'evidence.create':
      return change('/v1/evidence/claims', {
        expected_version: version(p),
        ...pick(p, [
          'claim_type',
          'requirement_keys',
          'statement',
          'job_related_purpose',
        ]),
      })
    case 'evidence.revoke':
      return change(`/v1/evidence/claims/${id(p.id)}/revoke`, {
        expected_version: version(p),
        reason: p.reason || 'REVOKED_BY_OWNER',
      })
    case 'consent.revoke':
      return change(`/v1/consents/${id(p.id)}/revoke`, {
        expected_version: version(p),
        reason: p.reason || 'REVOKED_BY_OWNER',
      })
    case 'consent.terms':
    case 'consent.evidence': {
      const vacancy = await api.get<ApiSchema['VacancyOut']>(
        `/v1/vacancies/${id(p.vacancyId)}`,
      )
      const common = {
        vacancy_id: vacancy.id,
        expected_version: version(p),
        terms_hash: p.terms_hash ?? vacancy.terms_hash,
        expires_at: p.expires_at,
        checkbox_confirmed: p.checkbox_confirmed,
      }
      if (action === 'consent.terms')
        return change('/v1/consents/terms', {
          ...common,
          candidate_expected_version: p.candidate_expected_version,
          scope: p.scope,
        })
      return change('/v1/consents/evidence', {
        ...common,
        claim_id: id(p.claimId),
        claim_expected_version: p.claim_expected_version,
        org_id: vacancy.org_id,
        kind: p.kind,
        consent_text: p.consent_text,
      })
    }
    default:
      throw new GatewayError(
        422,
        'UNKNOWN_ACTION',
        'This action is not supported. Refresh the page.',
      )
  }
}
