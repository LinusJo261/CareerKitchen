# 05 — ALL matching, reliability, PACT, WITNESS and adaptive-allocation pseudocode

## 0. Core rules and definitions
```
VACANCY_FILL_TARGET = 0.999     # research objective, NOT verified guarantee
MAX_ACTIVE_DECISION_CARDS = 10 # platform ceiling, not desired target or recommended shortlist size
n_j = number of distinct candidates ACTUALLY DELIVERED to employer j
S_j = ordered planned shortlist of candidate IDs, some possibly never delivered
F_j(T) = Boolean verified employment start from delivered shortlist by fixed deadline T
P(F_j(T)) = joint scenario model estimate; NEVER confused with prospectively validated fact
```
Neither `candidate_interest` nor `offer_accepted` equals actual `F_j(T)`. Global R99 aims to maximize market-wide realized fills under limited attention and deadline constraints; it must prefer `cannot_certify` over an unsupported 99.9% assertion.

## 1. Ranker input, eligibility and retrieval
```python
@dataclass(frozen=True)
class SanitizedPairFeatures:
    candidate_id: UUID
    vacancy_id: UUID
    role_family: str
    skills: list[SkillEvidenceAlignment]   # only authorized and job-related
    availability_alignment: bool
    compensation_compatible: bool           # don't reveal candidate exact floor
    work_mode_alignment: float
    experience_alignment: float
    employer_workflow_state: str
    candidate_current_response_load: float
    vacancy_current_response_load: float
    candidate_reliability_history: aggregate_or_none # only lawful, vetted usage
    employer_reliability_history: aggregate_or_none  # lawful, reviewed
    # NEVER billing, protected audit, medical information, background check,
    # raw resume embeddings without explicit lawful purpose/consent, or private evidence blobs.

async def hard_feasible(candidate,job,time) -> Eligibility:
    if any([not candidate.ACTIVE, not job.ACTIVE, blocked_org,
            no_valid_legal_requirement, salary_below_private_floor,
            impossible_work_mode, essential_license_missing,
            expired_role, unsafe_or_banned_account, active_closed_cycle]):
        return INELIGIBLE(reason_codes)
    if ambiguous_mandatory_requirements_unverified:
        return NEEDS_HUMAN_CLARIFICATION  # do not silently reject
    return ELIGIBLE

async def sparse_retrieve(job,market,per_job_pool_limit):
    sql_filter = hard constraints AND active availability AND blocks
    candidates = ANN_or_SQL_retrieve(sql_filter, role+skills+location, bounded_k)
    add_candidates_from_explicit_existing_interest_and_unreviewed_waiting()
    remove_duplicates_by_user_identity()  # no cross-tenant leaks
    verify_full_hard_feasibility_each_candidate()
    return bounded_list_with_retrieval_quality_audit

async def generate_pair_features(candidate_ids,job_ids):
    fetch permitted structured fields only; lazy evidence summary under permission
    join within scoped tenant context; don't import protected audit tables
    return immutable features with feature_version, source timestamps, hash
```

## 2. Reciprocal probabilities and v1 baseline scorer
```python
@dataclass
class PairEstimate:
    a0: float   # candidate interested when candidate first
    aE: float   # candidate interested when employer previously interested
    b0: float   # employer interested when employer first
    bC: float   # employer interested when candidate previously interested
    p_interview: float
    p_offer_given_interview: float
    p_accept_given_offer: float
    candidate_survival: float
    vacancy_survival: float
    quality: float
    epistemic_uncertainty: float
    model_version: str

async def predict_pair(f:SanitizedPairFeatures):
    if calibrated_model_approved_for_cohort:
        predict separate directional probabilities with uncertainty and eligibility context
    else:
        use transparent, strictly bounded cold-start heuristic; label research estimate
    check all outputs finite, in [0,1], with model cutoffs <= current_time
    return PairEstimate(...)

async def score_v1(candidate,job,market_prices):
    REQUIRE hard_feasible(candidate,job).eligible
    p = predict_pair(features(candidate,job))
    downstream = p.p_interview * p.p_offer_given_interview * p.p_accept_given_offer
    survival = p.candidate_survival * p.vacancy_survival
    value_C_first = p.a0 * p.bC * downstream * survival * p.quality
    value_E_first = p.b0 * p.aE * downstream * survival * p.quality
    cand_price, emp_price = market_prices.for_cell(job.market_cell)
    congestion_job = market_prices.job_backlog(job.id)
    congestion_candidate = market_prices.candidate_backlog(candidate.id)
    score_C = value_C_first - (cand_price + p.a0*emp_price) - p.a0*congestion_job
    score_E = value_E_first - (emp_price + p.b0*cand_price) - p.b0*congestion_candidate
    best = argmax([('candidate',score_C),('employer',score_E)])
    return Proposal(pair,side=best.side,surplus=best.score,model=p.model_version)

async def update_dual_attention_prices(cell,rolling_window):
    for side in [CANDIDATE,EMPLOYER]:
        g=(observed_new_decision_load-capacity)/max(capacity,1)
        H=H+g*g
        price = clamp(price + g/sqrt(H+1), min=0, max=CONFIG_PRICE_CAP)
    for vacancy in cell:
        g=(waiting_plus_expected_pending-processing_capacity)/max(processing_capacity,1)
        congestion=clamp(congestion + g/sqrt(cumulative_g_sq+1),0,MAX)
    log immutable price history

async def clear_baseline_event(event):
    if event.already_consumed: return
    affected_actors,affected_cells = determine_incremental_scope(event)
    expire_invalid_cards_and_old_waiting_items()
    proposals=[]
    for actor_scope in free_slot_scopes(affected_actors):
        for pair in sparse_retrieve(actor_scope):
            score = score_v1(pair)
            if score.surplus>0 and not_hard_blocked: proposals.append(score)
    order by surplus descending, existing expressed-interest priority,
             age/urgency and stable deterministic tie_break
    for p in proposals:
        try: issue_first_mover_card(p)  # transactionally revalidate all constraints
        except capacity_or_stale_conflict: continue
    emit outbox events; update prices asynchronously
```
The v1 baseline remains the default *execution* path. Global optimizer must never revoke existing active cards merely because new scores changed.

## 3. Versioned PACT readiness and the failure decomposition
```python
async def pact_preflight(job,candidate,stage):
    checks = [
       Check('job_open_and_funded',cheap,employer_authority),
       Check('essential_requirement_feasibility',cheap,job_related),
       Check('compensation_work_mode_start_window',cheap,both_party_current_terms),
       Check('employer_policy_authorization',medium,exact_role_version),
       Check('candidate_current_terms_opt_in',medium,exact_role_terms),
       Check('evidence_claim_valid',expensive,issuer_and_expiration),
       Check('role_scoped_disclosure_consent',medium,recipient_specific),
    ]
    ORDER checks by estimated failure_prob / expected_check_cost subject to
          information dependencies, evidence sensitivity and rights
    for check in checks:
        if check.not_lawfully_permitted: return NOT_READY(REQUIRES_HUMAN_REVIEW)
        if check.fails: return NOT_READY(check.public_reason_code)
    return compile_current_short_lived_readiness_hashes()
```
Ordering is an approximation: a check cannot occur before a required consent and cheaper does not justify collecting unnecessary private data. `READY` is not `OFFERED` and not `HIRED`.

## 4. Reliability scenario model (single vacancy)
```python
@dataclass(frozen=True)
class RiskScenario:
    id: str
    weight: float
    candidate_conditional_success: dict[candidate_id, float]
    job_wide_failure_prob: float
    assumption_version: str

async def build_scenarios(vacancy, candidates, model_version):
    # Predict from historical observations ONLY for research; never read future labels.
    # Include shared adverse circumstances: employer cancellation, salary discrepancy,
    # start-date change, candidate simultaneous offers, decision delays, correlated
    # qualification uncertainty, nonresponse; do not create discriminatory strata.
    scenarios = scenario_estimator.estimate(...)
    validate sum(weight)==1, weights>=0, conditional probabilities in [0,1]
    validate all requirements and evidence scopes, calibration metadata
    return scenarios OR UNCALIBRATED

def model_nonfill_risk(job,shortlist,scenarios):
    # Valid only if conditional independence holds after conditioning on each z.
    risk=0.0
    for z in scenarios:
        conditional_none = 1.0
        for candidate in shortlist:
            p = z.candidate_conditional_success[candidate]
            conditional_none *= (1-p)
        scenario_failure=z.job_wide_failure_prob + \
            (1-z.job_wide_failure_prob)*conditional_none
        risk += z.weight * scenario_failure
    return clamp(risk,0,1)

def robust_upper_failure(job,shortlist,plausible_models):
    if not plausible_models or some_version_missing:
        return UNKNOWN
    return max(model_nonfill_risk(job,shortlist,m.scenarios) for m in plausible_models)
    # This is *model ambiguity robustness*, NOT a frequentist certified bound.

def optimistic_feasibility_bound(job,pool,MAX_N,plausible_models):
    # Hypothetical oracle: can assign best candidates per scenario, no competition.
    # Provides necessary infeasibility condition under assumed models.
    for each scenario:
        top = top MAX_N conditional-success eligible candidates
        best_scenario_failure = job_common_failure + (1-job_common_failure)*product(1-p)
    optimistic_failure = sum(z.weight * best_scenario_failure)
    if optimistic_failure > 0.001: return MODEL_INFEASIBLE_EVEN_WITH_ORACLE
    return UNKNOWN_NOT_PROVEN_FEASIBLE
```
In real life candidates may fail dependently even after conditioning; this can drastically understate risk. Model-specific plausible bound must never be labeled an empirical guarantee.

## 5. Reliability optimizer: smallest useful market-wide shortlists
```python
@dataclass
class AllocationObjective:
    expected_fills: float
    model_threshold_passes: int
    attention_cost_candidate: float
    attention_cost_employer: float
    latency_cost: float
    retained_quality: float
    unresolved_risk: float
    regret_or_competition_cost: float

def vacancy_plan_candidates(job,eligible_edges,model,max_n,user_caps):
    chosen=[]
    candidates = sorted(eligible_edges, by=estimated_marginal_risk_reduction)
    for candidate in candidates:
        if len(chosen)>=max_n: break
        if not_candidate_consent_for_reservation_or_candidate_unavailable: continue
        risk_before = robust_upper_failure(job,chosen,model.plausible_models)
        risk_after = robust_upper_failure(job,chosen+[candidate],model.plausible_models)
        if risk_before==UNKNOWN or risk_after==UNKNOWN:
            # Can still plan research shortlist but never certify
            evaluate_expected_fill_and_attention_without_reliability_claim()
        if opportunity_cost(candidate,other_roles)>marginal_market_benefit: continue
        if marginal_expected_benefit <= attention_cost: continue
        chosen.append(candidate)
        if risk_after is known and risk_after <= 0.001: break
    if chosen empty: return no_shortlist(reason_codes)
    return Plan(chosen, mode=RESEARCH_ONLY, risk=robust_upper_failure(...))

def global_market_allocator(jobs,candidates,active_commitments,scenario_models):
    # Real optimizer uses sparse candidate-role edges; never dense 100k*10k matrix.
    graph = retrieve_job_eligible_edges_and_current_commitments()
    FIX already-active human decisions / existing mutual commitments; don't reallocate them
    FIX consented current exclusive reservations; treat generic prospects as soft, not certain
    allocate initial candidates using scarcity-aware weighted b-matching/min-cost-flow:
       edge_weight = marginal_expected_fill + quality - attention - candidate_other_options
       constraints = role openings, candidate selected limits, employer 10-card ceilings,
                     exclusive reserves <=1 candidate globally, human authorizations
    for iteration up to CONFIG_EXCHANGE_STEPS:
       candidate_move = find_low-cost swap or augmenting path between 2..L jobs
       compute aggregate objective for all affected jobs including scenarios
       if improvement>threshold and no rights/conflicts: apply to shadow plan
       else break or try next candidate
    for job in jobs:
       prune redundant reserve members if removal preserves feasible objective
       produce ordered conditional release plan; status research_only or cannot_certify
    return GlobalPlan(all_jobs,stale_on_state_change=True)
```
Important: global matching may maximize expected hires while some jobs stay below high-reliability thresholds. Provide Pareto variants and show `fraction_jobs_meeting_modeled_threshold`, `population_coverage`, mean verified fills, attention and time separately. Don't optimize only easy jobs to inflate threshold-pass rate.

## 6. Scenario-diverse shortlist selection and competition
```python
marginal_gain(candidate,job,current_set) = \
    failure_risk(current_set) - failure_risk(current_set+[candidate])

candidate_competition_cost(candidate,current_market) = \
    expected_market_value_without_candidate_restriction - \
    expected_market_value_with_candidate_hard_reserved_for_job

score = marginal_gain - alpha*employer_effort - beta*candidate_effort - \
       gamma*latency - delta*candidate_competition_cost
```
Avoid 'diversity of demographic status' as an algorithmic objective or shortcut. Scenario diversity means **independently evidenced failure modes**, not protected identities or stereotype-proxy cohorts. Keep employer and candidate choice protected; do not force someone into lower-preference role to improve aggregate metric.

## 7. WITNESS action-certificate planner
```python
@dataclass
class WitnessCertificate:
    affected_role_ids: list[UUID]
    new_edges_if_prerequisites_pass: list[Edge]
    prerequisites_and_or_graph: DependencyDAG
    role_version_hashes: dict[role_id,str]
    human_actor_authorizations_needed: list[ActorPermission]
    estimated_market_gain_distribution: Distribution
    predicted_candidate_attention: float
    predicted_employer_attention: float
    delay_cost: float
    irreversible_cost: float

async def compile_witnesses(state, baseline_allocation):
    bottlenecks = find_unfilled_jobs_and_high_common_failure_and_conflicted_edges()
    for job in bottlenecks:
        enumerate short augmenting paths and alternating cycles in sparse graph
        annotate blocked_edges with precise, eligible prerequisite types:
          - ask employer whether requirement truly optional; needs scoped signatory approval
          - candidate consent for existing verified evidence; no disclosure until consent
          - permitted candidate preference clarification; no coercive messaging
          - legitimate employer availability/compensation/authorization correction
        compress identical prerequisites that apply to explicitly enumerated role versions
        build AND/OR dependency DAG (approval + proof + actual preference both required)
        estimate upper-bound attainable allocation lift, common failure reductions,
                 review costs and time-to-result under models
        prune if optimistic upper gain < unavoidable costs OR human authorization impossible
        yield top-M candidate WitnessCertificate objects

async def score_witness_bundle(bundle,state,baseline):
    # Must compare the COMPLETE conditional action plan, not one prerequisite alone.
    future_utility=0
    for modeled outcome in sample_approval_and_proof_and_response_outcomes(bundle):
        future_state=simulate_outcome_on_isolated_copy(state,outcome)
        future_utility += outcome.prob * market_value(reoptimize(future_state))
    expected_gain = future_utility - expected_baseline_continuation(state)
    costs = employer_questions + consented_evidence_checks + candidate_attention + \
            delay + irrevocable_commitment_risk + external_candidate_opportunity_cost
    return expected_gain - costs, uncertainty_interval

async def ask_witness_question(bundle):
    REQUIRE policy mode PILOT, actual authorized employer opt-in to question process
    propose to human; no auto-approve; IF employer declines -> discard action
    IF approves scoped policy: conditionally request candidate proof/consent
    AFTER each human response: resnapshot and replan
    IF all conditions valid: propose normal first/second mover introduction
    otherwise revert to baseline or return cannot_certify
```
No fixed short horizon magically solves all complementarity. Factor prerequisites, share only valid scopes, bound computation, and allow abstention.

## 8. Dynamic exposure / timing controller
```python
async def propose_next_actions(state,baseline_proposal,portfolio,witnesses):
    actions = [WAIT,baseline_proposal] + portfolio.next_conditional_intro_actions + witnesses
    allowed=[]
    for a in actions:
        if current_user_selected_caps_full or role_caps_full: continue
        if a.exposes_candidate_without_permitted_consent: continue
        if a.is_new_exclusive_reservation and candidate_exclusively_reserved_elsewhere: continue
        if any essential eligibility condition missing: continue
        allowed.append(a)
    if not allowed: return baseline_if_valid_else_WAIT
    for a in allowed:
        estimate future filled roles and quality via bounded rollouts
        subtract separately priced candidate/employer minutes, opportunity loss, delay
        compute robust advantage lower bound versus BASELINE continuation
    choice=argmax(safe_lower_bound_advantage)
    IF choice positive and PILOT_authorized: return human_approved_action_proposal(choice)
    ELSE: return baseline_if_valid_else_WAIT

async def follow_up_after_event(event):
    if approved_rejection_or_expiry:
        update posterior with source/consent, release unused exclusive reserve
        recalc failure risk and candidate availability
        issue next reserved introduction ONLY if active caps free and human consent valid
    if employer partially filled role:
        decrement vacancy openings, recompute only remaining capacity
    if model drift or scenario dependence unknown: cannot_certify + baseline mode
```
Here `actual active-card count` is endogenous, bounded by selected user maxima (never larger than 10); `n` is measured by distinct employer-visible candidate deliveries over the agreed window.

## 9. Shadow mode, executor gate and audit
```python
async def shadow_on_baseline_event(committed_baseline_event):
    immutable_snapshot=build_privacy_safe_snapshot(committed_baseline_event.state_version)
    persist snapshot hash and baseline proposal hash
    launch background bounded planner(immutable_snapshot), outside baseline TX
    proposed = run_Global_R99_PACT_WITNESS(snapshot)
    check no write permissions in planner db principal; no network notifications
    persist internal shadow differences, runtime, missing permissions, reasons
    ASSERT live state/events/counters unchanged by planner

async def execute_pilot_proposal(proposal, actor):
    require scoped pilot flag and signed human acceptance
    BEGIN DB TRANSACTION:
      load latest role + candidate + consent + evidence + capacities
      IF state_hash mismatched or any readied proof stale: return RETRY_OR_BASELINE
      IF predicted_risk threshold is merely research: don't issue public reliability claim
      IF proposal involves question: create human-authored question action only
      IF proposal involves card: call core `issue_first_mover_card` inside this TX
      append exposure audit, full plan provenance, outbox events
    COMMIT
```
No advance authorization may silently create a mutual match or actual employment start.

## 10. Empirical prediction, calibration and reliability gate
```python
async def train_models(records):
    only properly licensed/permitted data; data minimization; deidentify
    split chronologically by EARLIEST OBSERVABLE PRE-INTRODUCTION EVENT,
          not first offer/interview; exclude processes lacking early evidence from intro prediction
    features must be present as-of decision time; disallow downstream stage leakage
    train baseline heuristic, logistic, gradient boosting; keep best external calibration
    evaluate AUROC, AUPRC, log loss, Brier, ECE, time decay and subgroup outcomes
    make dataset/model cards, drift monitors, coverage; do not confuse observational
    offer acceptance with actual employment starts or with TEN counterfactual outcomes

async def can_issue_reliability_claim(cohort,job,plan,target=.999):
    if not prospective_approved_trial: return CANNOT_CERTIFY('no_prospective_outcomes')
    if no_verified_employment_starts: return CANNOT_CERTIFY('proxy_only')
    if no_defensible_joint_calibration_or_common_failure_model:
        return CANNOT_CERTIFY('unmodeled_correlation')
    if not sufficient_comparable_sample_size_or_valid_CI:
        return CANNOT_CERTIFY('insufficient_evidence')
    if active_drift_or_selection_bias_or_policy_change:
        return CANNOT_CERTIFY('distribution_shift')
    if not full_coverage_accounted_for or job outside validated_cohort:
        return CANNOT_CERTIFY('population_mismatch')
    if statistically_valid_lower_bound_fill_probability < target:
        return CANNOT_CERTIFY('threshold_not_met')
    if compliance_human_signoff_missing:
        return CANNOT_CERTIFY('not_approved')
    return VALIDATED_RELIABILITY_STATEMENT_WITH_EXACT_COHORT_DATE_LIMITS
```
Do not apply a naive 2995 zero-failure rule as a universal authorization certificate. It's only a binomial idealization, not a per-job guarantee; real recruitment has selection, group dependencies and changing conditions. Log reasons for refusals without exposing private or protected data.

## 11. Metrics, bounds, ablation, and performance
```python
record_metric('verified_fill',start_verified & candidate_delivered_before_T)
record_metric('primary_fill_denominator',ALL trial enrolled vacancies whose deadline passed,
              include closed/zero shortlist/never offered)
record_metric('delivered_n',unique(candidate_id per vacancy with actual employer disclosure))
record_metric('candidate_attention',human minutes or count of candidate actions)
record_metric('employer_attention',human minutes or count of employer actions)
record_metric('shortlist_model_nonhire_risk',research_only)
record_metric('unsupported_certification_count',must_always_equal_0)
record_metric('time_to_verified_start',date_started - enrolled_date)
record_metric('fairness_and_accessibility',restricted,group safe audit)

benchmark_arms = [
   'actual_v1_baseline', 'greedy_top_n', 'global_weighted_matching',
   'global_r99_only', 'pact_preflight_only', 'witness_only',
   'global_r99_plus_pact', 'global_r99_pact_witness_dynamic'
]
for every arm: use same pre-registered market cohorts, opportunity constraints,
  candidate effort budgets and timing; prevent future label leakage; report CI and harms.

PERFORMANCE PLAN:
  - partition candidates/jobs by market cell and eligible sparse edges
  - build job shortlist tasks in bounded batches, cached feature hashes
  - use min-cost flow/b-matching for initial allocation, local exchange max steps
  - scenario rollouts top-M candidates/questions only, bounded wall-clock
  - use dual attention prices for early pruning, stale-state invalidation
  - avoid expensive optimization in response transactions; recheck fast executor
  - if timeout/unsupported model, run v1 fallback without changing issued cards
```

## 12. Exact `n` control, delivery accounting and definition of success
```python
async def choose_n_and_release_plan(vacancy, market, deadline_T):
    # Do NOT set n=10 by default; 10 limits ACTIVE cards, not total cumulative delivery.
    shortlist = global_plan_for_vacancy(vacancy)
    delivered_unique = set(load_exposure_events(vacancy,recipient_side=EMPLOYER))
    while vacancy.is_open and now() < deadline_T:
        if verified_start_exists_from_delivered(vacancy): return FILLED, len(delivered_unique)
        if current_employer_active_cards(vacancy) >= min(10,vacancy.max_active): WAIT
        next_candidate = first_available_unreleased_candidate(shortlist)
        if no_candidate_or_no_positive_expected_value: WAIT_OR_REPLAN
        if consent_or_feasibility_changed: replan; continue
        if expected_margin_below_cost_or_release_budget_exhausted: STOP
        issue_normal_bidirectional_card_via_transactional_executor(next_candidate)
        # On confirmation the candidate is *actually shown* to employer:
        if employer_visible_exposure_event_committed:
            delivered_unique.add(next_candidate.id)
        wait for response/timeout or scheduling interval; update beliefs
    return job_outcome_by_deadline, len(delivered_unique)
```
A candidate-first card shown ONLY to a candidate is not yet a delivered candidate to the employer until the candidate expresses interest and an employer-visible card/profile is issued. However, **candidate attention costs and earlier attempts must still be counted** and reported separately to avoid hiding failed contacts. In a prospective study, register both the employer-delivered count and total cross-side attempts; if using the strict whole-protocol reliability metric, include every enrolled role even when `n_delivered=0`.
