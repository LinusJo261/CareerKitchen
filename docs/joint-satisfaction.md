# Joint employee and manager satisfaction

The offline satisfaction trainer now supports one target from two direct reports
about the same employment spell. The selected policy takes the **lower rating**.
Both original ratings are retained. A high employee rating cannot hide a low
manager rating, or the reverse.

This target is distinct from employee-only NLSY97 satisfaction, synthetic skill
relevance and mutual interest before hiring. It has no live matching integration.

## Score definition

Each response scale must declare five codes ordered worst to best. The preparer
normalizes those codes to ordinal indices 0–4, then calculates:

```text
joint_rating = min(employee_rating, manager_rating)
joint_score = 25 * joint_rating
```

The resulting policy index has values 0, 25, 50, 75 or 100. It is not a percentage
chance of matching, and the category gaps are not measured equal satisfaction
intervals. Taking the minimum is a chosen policy, not learned weights or evidence
that this composite predicts hiring success.

For two instruments using 1 worst through 5 best:

| Employee response | Manager response | Lower response | Internal joint rating | Score index |
| --- | --- | --- | --- | --- |
| 5 | 5 | 5 | 4 | 100 |
| 5 | 2 | 2 | 1 | 25 |
| 3 | 4 | 3 | 2 | 50 |
| 5 | 1 | 1 | 0 | 0 |
| 5 | Missing | Unknown | null | null |

The default raw-code mapping is 1 worst through 5 best for both parties. The
NLSY97 employee question has the reverse coding; raw codes must be mapped from
their actual instrument. Never treat its raw code 1 as low satisfaction.
Manager ratings must be direct manager reports, not generated predictions,
promotion, pay growth, retention or a candidate's guess about their manager.

The Python helper `scripts.joint_satisfaction_label.joint_satisfaction(...)`
accepts already normalized 0–4 indices. It returns both originals, `joint_rating`,
`joint_score`, `aggregation: minimum` and a status. Missing responses produce
`MISSING_EMPLOYEE`, `MISSING_MANAGER` or `MISSING_BOTH`, with a null joint label.
It accepts only the selected minimum policy.

## Start with three CSV files

You can collect actual worker/manager reports without launching the app. Use
employees and their direct managers who can describe the same real jobs and
authorize use of their responses. These data must be linked from the outset;
unrelated NLSY97 respondents and synthetic Hugging Face profiles cannot be made
into genuine paired outcomes by assigning them common IDs.

```bash
.venv-research/bin/python -m scripts.join_joint_satisfaction init
```

This creates empty templates under `.local/joint-satisfaction/collection/`:

| File | Fill with |
| --- | --- |
| `feature_snapshots.csv` | One frozen worker/job feature vector per employment spell |
| `employee_ratings.csv` | The employee's own satisfaction response and collection/reference month |
| `manager_ratings.csv` | The direct manager's own satisfaction response, rater ID and dates |
| `mapping.json` | Actual source/release/instrument reference and rating-code directions |
| `collection_instructions.md` | Survey questions, scale, IDs and collection instructions |

The CSVs contain headers only. Nothing is presented as a real response until
actual observations are entered. Existing collection files are never overwritten.
Use pseudonymous IDs and keep contact/name lookup files separately. Confirm the
manager relationship and permission to use the records outside these tools.

Collect the ten inputs from information available before or at job start.
`scripts.mutual_matching_features.build_features` can calculate skill coverage
and relevant experience from confirmed structured data. Leave unknown inputs
blank, rather than inventing alignment scores. In retrospective collections,
today's preferences must not stand in for undocumented preferences at hiring.

Ask both participants about the same agreed reference month, for example six
months after job start. The suggested questions are:

- Employee: "Overall, how satisfied were you with this job during that month?"
- Direct manager: "Overall, how satisfied were you with this hire during that month?"

Use the same five ordered anchors: very dissatisfied, dissatisfied, neither,
satisfied, very satisfied. Record the actual wording and scales in the instrument
reference. This is a proposed collection instrument, not a validated survey.
Record when each response was actually collected, even when it concerns an
earlier month. Do not backdate newly collected ratings.

Every CSV uses `person_id`, `employer_id` and `job_started_at` to identify the
employment spell. Ratings also use `reference_at`; the same employer alone is
not a valid join. For a return to the same employer, use the new start month.
Ambiguous distinct spells within one month require resolution before import.
Each response has a unique `response_id` and direct-report `kind`; manager rows
also have a pseudonymous `rater_id`. There is no response row for an unanswered
request. Collected refusals may use a declared missing code.

After entering actual records and replacing source placeholders in the mapping:

```bash
.venv-research/bin/python -m scripts.join_joint_satisfaction join \
  --input .local/joint-satisfaction/collection \
  --output .local/joint-satisfaction/joined-1
```

The join uses exact person/employer/start keys and reference months. It preserves
missing sides and feature-only spells without assigning a joint label. Reports
for different months stay separate, incomplete observations. It rejects duplicate
keys, duplicate response IDs, ratings with no matching frozen feature record,
unexpected CSV columns, non-direct reports and invalid dates/features. Unknown
features remain null. Two collected missing responses retain their reference
periods, so separate follow-ups do not collapse into one record.

The destination must be new. The complete bundle is staged and published only
after preparation succeeds. It contains `ratings.jsonl`, the source mapping,
`join_report.json` and `prepared/observations.csv`, `prepared/mapping.json`,
`prepared/preparation_report.json`. Input CSVs remain unchanged. Reports include
source hashes, counts and missingness, not respondent identities. The JSONL and
prepared CSV retain pseudonymous response provenance in ignored local storage.

For a newly collected pilot from one time period, the explicit joint-only pilot
mode trains/evaluates using separate worker groups without pretending to test
future years:

```bash
.venv-research/bin/python -m scripts.satisfaction_research train \
  --input .local/joint-satisfaction/joined-1/prepared/observations.csv \
  --mapping .local/joint-satisfaction/joined-1/prepared/mapping.json \
  --split-policy grouped-pilot \
  --output .local/joint-satisfaction/pilot-run-1
```

Pilot mode does not accept temporal cutoffs. Stable 70/15/15 worker hash groups
keep a worker's jobs in one fold; employer identities may overlap. Missing labels
are still excluded. All folds must have usable paired observations and training
must include at least two target categories and some known inputs. Preserve
IDs/seed and the test holdout rather than changing them to improve the score.
Artifacts explicitly state there was no forward-time evaluation. This supports
an initial offline pilot, not a claim about future production performance.
The default `grouped-temporal` mode below remains available for genuine dated
cohorts; existing employee-only NLSY97 experiments retain their original policy.

## Prepare paired reports

From the repository root:

```bash
.venv-research/bin/python -m scripts.prepare_joint_satisfaction init
```

This creates an empty `ratings.jsonl` and mapping template under
`.local/joint-satisfaction/input/`. Existing files are protected. Set the actual
source name, collection release and instrument reference in `mapping.json`.
The template intentionally refuses preparation while those fields contain
`REPLACE` placeholders. Actual paired data uses source kind
`paired_direct_ratings`; software fixtures must use `fictional_fixture`.

Each JSONL line is one worker/job/follow-up record with exactly these top-level
fields. This example is **fictional**, expanded for readability:

```json
{
  "person_id": "fictional-person-1",
  "employer_id": "fictional-employer-1",
  "job_started_at": "2020-01",
  "feature_as_of": "2020-01",
  "features": {
    "required_skill_coverage": 1.0,
    "preferred_skill_coverage": 0.75,
    "relevant_experience_years": 3.0,
    "experience_requirement_coverage": 1.0,
    "employer_role_preference_alignment": 0.8,
    "candidate_role_preference_alignment": 1.0,
    "candidate_work_mode_preference_alignment": 1.0,
    "candidate_employment_type_preference_alignment": 1.0,
    "candidate_compensation_preference_alignment": null,
    "candidate_schedule_preference_alignment": null
  },
  "employee_rating": {
    "response_id": "fictional-employee-response-1",
    "person_id": "fictional-person-1",
    "employer_id": "fictional-employer-1",
    "job_started_at": "2020-01",
    "reference_at": "2020-07",
    "observed_at": "2020-07",
    "value": 5,
    "kind": "direct_employee_report"
  },
  "manager_rating": {
    "response_id": "fictional-manager-response-1",
    "rater_id": "fictional-manager-1",
    "person_id": "fictional-person-1",
    "employer_id": "fictional-employer-1",
    "job_started_at": "2020-01",
    "reference_at": "2020-07",
    "observed_at": "2020-08",
    "value": 2,
    "kind": "direct_manager_report"
  }
}
```

The input file stores each object on one physical line. Use null for a missing
rating object; its counterpart is preserved without inventing a joint outcome.
Each rating repeats the worker/employer/start key so a different person's rating
cannot be silently attached by file order. IDs must be pseudonymous. A manager
report also has a manager rater ID; none of these identities are model inputs.
Source owners must establish that the person really supervised this worker and
that use of both responses is authorized. Declarations alone do not prove this.

Both known ratings must concern the same reference month and spell. They may be
collected in different months. The combined observation time is the **later**
collection month, preventing use of manager feedback before it was available.
The declared default follow-up is 3–24 months after starting; select an appropriate
study window before evaluation. All dates have actual month resolution, YYYY-MM.

Features must describe conditions known before or at job start. The ten fixed
pair features are documented in [mutual matching research](mutual-matching-research.md#inputs).
Use null for unknown features. Later performance, either satisfaction response,
manager identity and response metadata cannot enter the predictive matrix.

```bash
.venv-research/bin/python -m scripts.prepare_joint_satisfaction prepare \
  --input .local/joint-satisfaction/input/ratings.jsonl \
  --mapping .local/joint-satisfaction/input/mapping.json \
  --output .local/joint-satisfaction/prepared-1
```

The destination must be new. Outputs are `observations.csv`, `mapping.json` and
`preparation_report.json`. The CSV preserves normalized and raw ratings,
reference/observation dates, response provenance, label status and the joint score.
The report contains aggregate paired/missing/exclusion counts and input hashes.
Raw data remains untouched and all artifacts stay in ignored `.local/` storage.

The preparer rejects mismatched spell/period keys, duplicate response IDs,
duplicate spell/reference rows, unsupported scales, indirect reports, future
features, invalid timelines and unexpected input fields. Out-of-window outcomes
are excluded and counted. Missing sides stay unknown even when the other side
reports the highest rating.

## Train on the joint target

The existing satisfaction trainer accepts the prepared joint mapping. It
rechecks that every present joint label equals the lower of its two normalized
ratings. A survey export cannot be declared a paired direct-rating dataset just
by changing its target field. Source provenance still requires review.

Choose cutoffs appropriate to actual data; these dates are illustrative:

```bash
.venv-research/bin/python -m scripts.satisfaction_research train \
  --input .local/joint-satisfaction/prepared-1/observations.csv \
  --mapping .local/joint-satisfaction/prepared-1/mapping.json \
  --train-before 2022-01 --validate-before 2024-01 \
  --output .local/joint-satisfaction/trained-1
```

The training destination must also be new. Real artifacts are
`paired_joint_satisfaction_model.json` and
`paired_joint_satisfaction_report.json`. Fictional inputs produce explicitly
prefixed `fictional_joint_satisfaction_*` artifacts. Model/report target is
`joint_reported_satisfaction`, with the policy version and score-to-class mapping
saved. Earlier employee-only artifact names and labels are unchanged.

The classifier learns the five ordered joint categories. Its most likely class
maps to one score index through `[0, 25, 50, 75, 100]`; probabilities across those
categories are uncalibrated estimates, not a chance of hiring or matching.
Scaling/imputation fits only training data. Joint numeric features entirely
unknown during training are omitted and reported. At least one usable feature,
two training categories and nonempty evaluation folds are required.

The existing split keeps people separated and evaluates later job cohorts;
both ratings must be observed before the applicable training/validation cutoff.
The same employer may appear across folds. The first complete eligible paired
rating is selected for each person/employer/start spell, never the highest score.
Reports compare against the training-category baseline with category accuracy,
ordinal-step MAE, within-one-category accuracy, log loss and multiclass Brier score.

There are currently **no actual direct manager ratings in the downloaded NLSY97
export**. It cannot train this joint target by itself. No real joint model or
matching accuracy is claimed. Missing paired responses, rater differences and
selection into observed jobs remain evaluation limitations. This change creates
no frontend, live introductions, consent, employer feedback or employment outcomes.

```bash
.venv-research/bin/python -m unittest discover -s tests/research -q
```
