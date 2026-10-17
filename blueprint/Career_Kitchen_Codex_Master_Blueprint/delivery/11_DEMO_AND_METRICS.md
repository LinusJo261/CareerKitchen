# 11 — Demo scenario, analytics definitions and evaluation protocols

## Complete resettable fictional demo storyline
Fictional entities (seeded fixtures, no real candidate personal data):
- Employer: `Cascade Robotics` (fictional) with two positions: `Robotics Hardware Engineer` and `Embedded Systems Developer`.
- Candidate A: excellent relevant experience, needs compensation/start-date clarification.
- Candidate B: has verified relevant project evidence but no optional listed academic credential.
- Candidate C: strongly matches Embedded role, might be competing with Hardware role.
- Candidates D..H: distinct job-related qualifications, preferences and response availability.
- Employer signatory authorized only for Hardware vacancy version 2.
- Internal shadow model includes a rare modeled shared failure event, explicitly hypothetical.

### Reset
```python
async def reset_demo(seed="career-kitchen-demo-v1"):
    REQUIRE environment != PRODUCTION and current_actor developer_admin
    TRUNCATE fictional fixture tenant only, not arbitrary customer data
    set deterministic clock, RNG seed, role IDs, scenario inputs, outcome event coins
    INSERT org, verified fictional signatory, candidates, roles, initial consents
    role Hardware DRAFT, role Embedded ACTIVE
    return initial UI route + scenario fixture checksums
```

### Demo scenes
1. Employer sets role expectations: pay band, work mode, essential skills; PACT signatory signs versioned policy that permits certain evidence substitutions only if approved.
2. Candidate B uploads fictional sample project claim. Independent demo verifier marks it verified (clearly mock fixture); candidate grants role-specific disclosure. PACT readiness becomes valid.
3. Candidate A sees terms confirmation, corrects availability; candidate terms consent recorded. Changing salary afterwards invalidates consent.
4. Baseline V1 recommends a few candidates; Cards show employer-first or candidate-first route, not generic feed.
5. Candidate C clicks Interested -> waiting or employer review; employer Interested -> mutual match; chat unlocks; before mutual chat route returns forbidden.
6. Shadow Global R99 plots research-only modeled nonfill risk for alternative shortlists, shows that the same candidate cannot be exclusively promised to both employers.
7. WITNESS identifies a requirement classified `AMBIGUOUS`, requests scoped signatory clarification, and illustrates Approve and Deny branches. No silent waiver.
8. Optimizer chooses variable n and conditional release; UI shows how many candidates are delivered to company vs reserved/unshown (different counters).
9. Offer acceptance and start verification separate; demo `START_CONFIRMED` only after simulated corroboration action. Display 'fictional demonstration' on all claims.
10. Explain reliability limit: cannot certify 99.9% from prototype; present observed attention/card metrics and validated test state instead.

### Demo telemetry generated from events, never fake constants
```python
stats = {
 "decision_cards_issued": count(decision.issued),
 "candidate_decisions": count(candidate_side decision.answered),
 "employer_decisions": count(employer_side decision.answered),
 "mutual_matches": count(pair.mutual),
 "offers": count(offer.issued),
 "accepted_offers": count(offer.accepted),
 "verified_starts": count(employment_start.verified),
 "n_per_vacancy": distinct_candidate_exposure_count(vacancy, employer_visible=True),
 "pact_questions": count(pact.clarification_requested),
 "model_research_flags": count(shortlist.research_estimate),
 "unsupported_99_9_guarantees": 0
}
```

## Primary prospective evaluation
- Unit: vacancy enrolled *before* algorithm allocates candidates.
- Outcome: verified employment start within prespecified deadline `T`, from candidate actually exposed by Career Kitchen to that vacancy.
- Denominator: every enrolled vacancy whose deadline has passed, including zero-shortlist, employer cancel, no response, and candidates hired elsewhere; break down causes separately.
- Metrics: vacancy fill rate and confidence interval; candidates shown per vacancy (p50/p90); candidate/employer decision count and minutes; time-to-start; validated quality/retention if lawfully available; opportunity/candidate welfare; access and accommodation metrics; review override/fairness measures.
- Pilot governance: pre-register cohorts, deadline, selection policy and exclusions; avoid post-hoc restricting to easy jobs; instrument true exposure/consent.
- Experimental arms: v1 baseline, top-N independent, global weighting, R99-only, PACT-only, WITNESS-only, integrated. Randomize employers/vacancies only where ethically and legally appropriate and where harms controlled.
- No interpreting JTH historic job offers as randomized tests or actual employment starts.
- For hypothetical binomial independent outcomes only, zero failures among ~2995 comparable vacancies gives a one-sided lower bound around .999; dependence and heterogeneity invalidate naive application.

## Interpretations
```
MODEL P(reliable shortlist) >= .999  -> 'passes an assumed simulation threshold'
OUT-OF-SAMPLE accepted-offer model -> 'predicts historical offer-accepted label'
REAL prospectively verified starts -> 'observed job starts within this cohort/window'
STATISTICALLY validated .999 -> requires calibration, confidence, populations, independence
                              / dependence considerations, governance signoff
```
No UI or demo copy should collapse these categories.

## Product/demo rubric mapping (without fabricated scores)
- Functionality: real persisted decision cards, PACT approval and revocation, two-sided chat gating, duplicate state robustness.
- Design: simple candidate/employer decisions, clear privacy/consent, accessible responsive interface.
- Creativity: hiring as a scarce two-sided market, variable active exposure, failure-mode-aware portfolio selection and WITNESS prerequisite plans.
- Track applicability: map only to actual chosen hackathon sponsor track requirements; don't fabricate compliance.
- Presentation: visualize real branching state transitions; show causal story of an employer vacancy and candidate choices; avoid excessive '99.9% guaranteed' claim.
