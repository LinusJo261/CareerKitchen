# Offline mutual-interest research

This experiment learns from a candidate–vacancy pair's structured experience,
requirements and stated preferences. Its target is **both participants explicitly
answering Interested within a declared horizon after the first decision card is
issued**. The initialized manifest uses 14 days. It does not predict hiring,
offer acceptance, a verified start or job satisfaction.

The implementation is `scripts/mutual_matching_research.py`, with pure feature
calculations in `scripts/mutual_matching_features.py`. It does not connect to the
API or replace the live compatibility scorer. It cannot issue introductions,
change consent, bypass essential evidence, or alter double opt-in or attention
ceilings. Research inputs and outputs belong under ignored `.local/` storage.

## Inputs

Every feature object must contain exactly these ten names. Use JSON `null` for
unknown or not applicable, never an invented score. Values are finite numbers;
booleans, text, negative numbers and undeclared fields are rejected.

| Feature | Meaning | Range |
| --- | --- | --- |
| `required_skill_coverage` | Fraction of declared required skills present in confirmed candidate skills | 0–1 or null |
| `preferred_skill_coverage` | Fraction of declared preferred skills present in confirmed candidate skills | 0–1 or null |
| `relevant_experience_years` | Elapsed years in confirmed role-relevant experience available at the feature cutoff | Nonnegative or null |
| `experience_requirement_coverage` | Relevant years divided by the employer's declared minimum, capped at one | 0–1 or null |
| `employer_role_preference_alignment` | Alignment with the employer's stated role/background preferences | 0–1 or null |
| `candidate_role_preference_alignment` | Alignment with the candidate's stated role preferences | 0–1 or null |
| `candidate_work_mode_preference_alignment` | Alignment with the candidate's remote/hybrid/onsite preferences | 0–1 or null |
| `candidate_employment_type_preference_alignment` | Alignment with the candidate's employment-type preferences | 0–1 or null |
| `candidate_compensation_preference_alignment` | Offered compensation relative to stated candidate preferences, using compatible currency and pay period | 0–1 or null |
| `candidate_schedule_preference_alignment` | Alignment with the candidate's stated schedule preferences | 0–1 or null |

`build_features(...)` is a Python helper, not an automatic profile exporter. It
accepts confirmed canonical skill names, required/preferred skill names,
confirmed relevant experience date intervals, an optional experience minimum,
a date cutoff and the six supplied preference alignments. Skill names normalize
case and whitespace; curated aliases must be resolved by the caller. It does not
infer skills, experience relevance or employer interest from prose.

Empty requirements produce null coverage. Unknown candidate skills also produce
null; a confirmed empty skill list produces zero against nonempty requirements.
Unknown experience is null; a confirmed empty relevant history is zero. Overlap
between jobs is counted once. Experience ends are clipped at the cutoff, ongoing
jobs stop at the cutoff, and future starts or reversed intervals are rejected.
Elapsed days are divided by 365.25. A missing or zero experience minimum produces
null experience-requirement coverage.

Required-skill coverage is descriptive: it does not establish that every lawful
essential requirement has current evidence. Eligibility remains a backend gate.
The six preference alignments describe information stated before this
introduction; they are **not** the current pair's Interested answers. Their
definitions and source evidence must be consistent across an exported dataset.

## Training data contract

Run all commands from the CareerKitchen repository root using the existing
research environment. NumPy is required; the script does not need an API server
or database connection.

```bash
.venv-research/bin/python -m scripts.mutual_matching_research init
```

This creates three files under `.local/mutual-matching/input/`:

- `manifest.json`: source, target, feature version and outcome horizon.
- `introductions.jsonl`: initially empty; one complete JSON object per line.
- `prediction_input.json`: all ten unknown features and eligibility set to
  `NEEDS_CLARIFICATION`.

`init --output PATH` changes the destination. It refuses a nonempty directory.
Replace manifest placeholders with actual export metadata before validating or
training. The export timestamp must be at least as late as every observation.
A complete **fictional illustrative manifest** is:

```json
{
  "schema_version": 1,
  "target": "mutual_opt_in_within_horizon",
  "feature_version": "mutual-pair-features-v1",
  "horizon_days": 14,
  "source": {
    "kind": "fictional_fixture",
    "dataset": "fictional_documentation_example",
    "source_version": "example-v1",
    "exported_at": "2024-03-20T00:00:00Z"
  }
}
```

For actual observations, use `source.kind: "observed_introduction_outcomes"`
with the actual dataset name, export version and timezone-aware export time.
The horizon must be an integer from 1 through 365, chosen before evaluation.

Each introduction record requires exactly the following fields. This complete
row is **fictional**, formatted across lines for readability. JSONL files must
store each complete object on one physical line.

```json
{
  "cycle_id": "fictional-cycle-1",
  "candidate_id": "fictional-candidate-1",
  "vacancy_id": "fictional-vacancy-1",
  "organization_id": "fictional-organization-1",
  "candidate_version": 2,
  "vacancy_version": 3,
  "feature_as_of": "2024-03-01T09:00:00Z",
  "first_exposed_at": "2024-03-01T10:00:00Z",
  "first_mover": "candidate",
  "policy_version": "fictional-sequential-policy-v1",
  "eligibility": "ELIGIBLE",
  "observation_status": "OBSERVABLE",
  "observed_at": "2024-03-10T00:00:00Z",
  "features": {
    "required_skill_coverage": 1.0,
    "preferred_skill_coverage": 0.5,
    "relevant_experience_years": 3.0,
    "experience_requirement_coverage": 1.0,
    "employer_role_preference_alignment": 0.8,
    "candidate_role_preference_alignment": 1.0,
    "candidate_work_mode_preference_alignment": 1.0,
    "candidate_employment_type_preference_alignment": 0.8,
    "candidate_compensation_preference_alignment": 0.7,
    "candidate_schedule_preference_alignment": null
  },
  "decisions": {
    "candidate": {
      "status": "INTERESTED",
      "issued_at": "2024-03-01T10:00:00Z",
      "answered_at": "2024-03-02T10:00:00Z"
    },
    "employer": {
      "status": "INTERESTED",
      "issued_at": "2024-03-02T10:00:00Z",
      "answered_at": "2024-03-04T10:00:00Z"
    }
  }
}
```

IDs are pseudonymous joins/grouping fields, never predictors. Export one frozen
row per cycle; duplicate cycle IDs are rejected. Profile and vacancy versions
must be positive integers. All timestamps include a timezone, and
`feature_as_of <= first_exposed_at <= observed_at <= source.exported_at`.
`observed_at` is the time when the row's decision statuses and exclusion state
were known, not a global export timestamp copied onto earlier observations.
An exporter must preserve that point-in-time state even if the cycle later
changes. The separate manifest timestamp records when the file was exported.
The first mover is `candidate` or `employer`; its card is issued exactly at
`first_exposed_at`. A second card can be issued only after the first participant
explicitly opts in, matching the backend's sequential workflow.

Each side's decision has exactly `status`, `issued_at` and `answered_at`:

- `NOT_ISSUED`: both timestamps null.
- `PENDING`, `EXPIRED`, `CANCELLED`: issuance is known; answer is null.
- `INTERESTED`, `PASSED`: issuance and explicit answer timestamps are known,
  ordered and no later than observation.

`eligibility` is `ELIGIBLE`, `INELIGIBLE` or `NEEDS_CLARIFICATION`.
`observation_status` is `OBSERVABLE`, `CANCELLED`, `TERMS_CHANGED` or `WITHDRAWN`.
Rows must still be structurally valid when their outcome is excluded.

Labels are derived, not supplied as predictive features:

- Positive: both actual responses are `INTERESTED` inside the horizon, inclusive
  of the deadline.
- Negative: an actual `PASSED` response occurs inside the horizon.
- Excluded: ineligible or unclear pairs; cancelled, withdrawn or changed-term
  observations; expired or cancelled decisions; late outcomes; unresolved rows.

A single Interested answer is not a mutual match. A pending or expired card is
not an explicit rejection. Cancellation or changed terms exclude the row even
if another status might otherwise produce a label.

The timestamp checks do not reconstruct history or prove provenance. Export
consented point-in-time snapshots; never join an old decision to today's edited
profile. Do not include this cycle's responses, response times, interview/offer
results, later employment experience or post-exposure preferences as inputs.
NLSY97 satisfaction and the Hugging Face skill-relevance labels cannot supply
actual two-sided opt-in labels for this experiment.

## Validate, train and inspect results

```bash
.venv-research/bin/python -m scripts.mutual_matching_research validate \
  --input .local/mutual-matching/input/introductions.jsonl \
  --manifest .local/mutual-matching/input/manifest.json
```

Validation reports source cycles, labeled cycles and exclusions. It fails when
no usable explicit decisions exist. The initialized empty file is therefore not
trainable. Choose real date cutoffs suited to the observed data; these dates
are illustrative:

```bash
.venv-research/bin/python -m scripts.mutual_matching_research train \
  --input .local/mutual-matching/input/introductions.jsonl \
  --manifest .local/mutual-matching/input/manifest.json \
  --train-before 2022-01-01T00:00:00Z \
  --validate-before 2024-01-01T00:00:00Z \
  --output .local/mutual-matching/observed-run-1
```

The output directory must not exist. Actual-observation outputs are
`observed_match_model.json` and `observed_match_report.json`; fictional outputs
have the `fictional_` prefix. Artifacts include source/file hashes, split
settings, training settings, target, horizon, limitations, `fictional_data`,
`live_execution: false` and `estimate_kind: "EXPERIMENTAL_UNCALIBRATED"`.
Reports, model artifacts and prediction outputs explicitly declare
`estimation_population` as
`eligible_issued_introductions_with_explicit_resolution_within_horizon`.

Candidate and vacancy IDs are each deterministically assigned to 70/15/15 hash
groups with seed 42. A pair is retained only when both identities have the same
group and it meets that group's time condition:

- Training decision statuses and exclusion state must be observed
  (`observed_at`) before `train-before`.
- Validation introductions start at or after `train-before`, with labels
  and exclusion state observed (`observed_at`) before `validate-before`.
- Test introductions start at or after `validate-before`.

This keeps candidate and vacancy identities separated across folds and prevents
training outcomes or later cancellation/selection state crossing the first
cutoff. An earlier answer date alone does not establish when the exported state
was known. Many rows are deliberately dropped
by the intersection; the report counts them. Empty folds and single-class
training data fail. Organizations are **not** grouped out, so multiple vacancies
from one employer may appear across folds. Employer-disjoint evaluation remains
a separate extension.

The classifier uses two-class logistic regression through the existing NumPy
softmax implementation, without survey labels or survey weights. Defaults are
500 training epochs and L2 penalty 0.01; those defaults and seed are not current
CLI flags. Numeric scaling and median imputation are fitted only on training
rows, with a missing indicator per active feature. Entirely unknown training
features are omitted and listed in the report; they cannot become useful merely
by appearing at prediction time.

Validation and test results compare the model with a constant probability equal
to the training mutual-opt-in prevalence. The report contains log loss, Brier
score, accuracy, balanced accuracy, precision, recall, a confusion matrix
`[[TN, FP], [FN, TP]]`, positive counts and ten reliability bins. Class decisions
use a fixed 0.5 threshold. Undefined precision/recall or balanced accuracy is null.
Lower log loss and Brier score are better, but neither alone proves calibrated
probabilities. Review the bin counts and observed rates; calibration itself is
not fitted by this pipeline. See the official
[probability calibration guidance](https://scikit-learn.org/stable/modules/calibration.html).
Use validation results to choose changes and preserve the final test cohort;
preprocessing must not fit on evaluation data, as explained in the official
[data leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage).

These metrics cover **selected, resolved introductions**: mutual opt-ins versus
explicit passes inside the horizon. Excluding nonresponse creates selection and
censoring bias. Performance does not establish the unconditional match chance
for an arbitrary candidate–vacancy pair, or quantify matches among unexposed,
pending or expired pairs. There are no propensity corrections, confidence
intervals, ranking metrics or deployment guarantees in this implementation.

## Predict with a saved model

Prediction input has exactly three keys: `schema_version: 1`, `eligibility` and
`features` containing all ten names above. It contains no IDs or outcomes. For
an eligible, reviewed offline example, populate the initialized
`prediction_input.json` with known feature values and the appropriate eligibility.

```bash
.venv-research/bin/python -m scripts.mutual_matching_research predict \
  --model .local/mutual-matching/observed-run-1/observed_match_model.json \
  --input .local/mutual-matching/input/prediction_input.json
```

For eligible inputs and a compatible model, output includes
`status: "EXPERIMENTAL_UNCALIBRATED"`, `match_probability`, the horizon and whether
training data was fictional. An absent artifact returns `NOT_TRAINED` with a
null probability. Ineligible/unclear snapshots or entirely unknown active inputs
return `ABSTAIN` with a null probability. Invalid contracts or model artifacts
fail instead of being repaired silently. Prediction inputs have no timestamp
field; callers must ensure these features really are available before exposure.

A returned 0.7 is an uncalibrated model estimate. It does not establish that seven
out of ten such pairs will mutually opt in. Fictional training remains fictional
when making predictions.

## Software demonstration and remaining integration

```bash
.venv-research/bin/python -m scripts.mutual_matching_research demo \
  --output .local/mutual-matching/fictional-demo
```

This creates 180 deliberately simple fictional introductions and trains a demo
using separate fictional candidate/vacancy groups and time cohorts. Its output
directory must be new. Demo scores validate software behavior, not real matching
quality, and must not be presented as observed performance.

The backend already stores profile experience, some candidate preferences,
vacancy terms, requirements and actual decision events. This module does not
export them. Structured role-relevant experience, employer experience targets,
ranked preferences, schedule preferences and a consented historical snapshot
exporter require separate backend implementation. Existing binary acceptable
preferences often become constant after hard eligibility filtering; they are
not already meaningful graded preference scores. Historical interest aggregates,
if later added, must use only earlier unrelated cycles and a versioned definition.
Current-cycle interest stays an outcome.

The first working step with actual app data is a reviewed export that satisfies
the contract. No real mutual-interest accuracy can be reported until suitable
observed outcomes exist and the grouped time splits are populated.
