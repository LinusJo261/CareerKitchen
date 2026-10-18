import type { ApiSchema } from '../workspace-types'

// Display state only. FastAPI remains authoritative for every disclosure.
export function currentClaim(
  claim: ApiSchema['ClaimOut'] | undefined,
  now = Date.now(),
) {
  return Boolean(
    claim &&
    claim.status === 'VERIFIED' &&
    claim.verified_at &&
    claim.expires_at &&
    Date.parse(claim.expires_at) > now,
  )
}

export function currentTerms(
  consent: ApiSchema['TermConsentOut'],
  vacancy: ApiSchema['VacancyOut'] | undefined,
  now = Date.now(),
) {
  return Boolean(
    vacancy &&
    vacancy.state === 'ACTIVE' &&
    !consent.revoked_at &&
    Date.parse(consent.expires_at) > now &&
    consent.vacancy_id === vacancy.id &&
    consent.role_version === vacancy.version &&
    consent.terms_hash === vacancy.terms_hash,
  )
}

export function currentDisclosure(
  grant: ApiSchema['EvidenceGrantOut'],
  vacancy: ApiSchema['VacancyOut'] | undefined,
  claim: ApiSchema['ClaimOut'] | undefined,
  now = Date.now(),
) {
  return Boolean(
    vacancy &&
    vacancy.state === 'ACTIVE' &&
    !grant.revoked_at &&
    Date.parse(grant.expires_at) > now &&
    grant.vacancy_id === vacancy.id &&
    grant.org_id === vacancy.org_id &&
    grant.role_version === vacancy.version &&
    claim?.id === grant.claim_id &&
    currentClaim(claim, now) &&
    (grant.kind !== 'DISCLOSE_DOCUMENT' || claim?.has_document),
  )
}
