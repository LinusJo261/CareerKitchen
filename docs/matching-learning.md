# Learning from explicit matching decisions

`scripts/matching_learning.py` trains a small reciprocal logistic model from
frozen introduction snapshots and actual decisions. It writes a new immutable
challenger and an evaluation report. Running it never activates a model, issues
cards, changes consent, or updates existing weights.

There is currently no measured real-world accuracy in this repository. A passing
software fixture verifies implementation. Synthetic relevance, allocation value,
survey satisfaction, and explicit mutual opt-in are different targets and cannot
substitute for one another.

## Target and data

The target is two explicit `INTERESTED` decisions within the manifest's declared
horizon after first exposure. One explicit `PASSED` decision within that horizon
is negative. Pending, expired, cancelled, withdrawn, changed-term, late, unclear,
and ineligible observations are excluded. Nonresponse is never a rejection.

Input uses the existing ten-field `mutual-pair-features-v1` JSONL/manifest contract
documented in [mutual-matching-research.md](mutual-matching-research.md). The trainer
reuses its strict timestamp, sequential opt-in, duplicate-cycle and label checks.
Only four fields currently available from the production compatibility snapshot
are used. The other six research fields never enter this model.

| Frozen input field | Portable model field |
| --- | --- |
| `preferred_skill_coverage` | `employer_skills` |
| `candidate_role_preference_alignment` | `candidate_role` |
| `candidate_work_mode_preference_alignment` | `candidate_work_mode` |
| `candidate_employment_type_preference_alignment` | `candidate_employment_type` |

Values are finite numbers in `[0, 1]` or null. IDs, decisions, timestamps and
policy names are grouping/provenance fields, never predictive inputs. Inputs must
be consented snapshots frozen before exposure, not reconstructions from today's
edited profiles. Source declarations and hashes establish traceability and
integrity; they do not independently prove that labels are genuine.

The estimate applies to eligible, historically issued introductions that resolve
explicitly within the horizon. It is not a probability of hiring or successful
employment, and does not establish how unexposed or nonresponding pairs behave.

## Fit and evaluate

Choose the horizon, date cutoffs and split seed before inspecting outcomes. From
the repository root, after obtaining an actual observed export:

```powershell
.venv-research/Scripts/python.exe -m scripts.matching_learning `
  --input .local/matching-outcomes/introductions.jsonl `
  --manifest .local/matching-outcomes/manifest.json `
  --train-before 2026-07-01T00:00:00Z `
  --validate-before 2026-09-01T00:00:00Z `
  --output .local/matching-models/challenger-001
```

These dates illustrate the command, not an existing training dataset. On Unix,
use `.venv-research/bin/python` and the shell's line continuation syntax.

The deterministic split policy `candidate-organization-forward-time-v2` assigns
stable candidate and organization hash groups before applying forward-time
cohorts. Each vacancy must belong to exactly one organization across the entire
source export, including unresolved or otherwise excluded rows. Keeping employers
disjoint therefore also keeps their vacancies disjoint. All vacancies posted by
a recurring employer share that employer's cohort; repeated employers do not
automatically make every refresh ineligible.

Rows outside their designated candidate/organization group and time cohort are
discarded and counted. Candidate, organization and vacancy disjointness are
checked before fitting. Policy version, grouping fields, identity counts, seed
and date cutoffs are frozen in artifact provenance and its integrity hash.
Training observations must be historically known before the training cutoff.
A global export time cannot be copied into every row's historical `observed_at`.
Organization overlap remains a fail-closed review check. The requirement for at
least 20 evaluation employers is unchanged: a small marketplace can still lack
enough genuinely independent employer observations to qualify a learned model.

Training rows alone determine median imputation, centering, scaling and logistic
coefficients. Explicit missingness is encoded separately. Four L2 strengths are
compared on validation log loss. Optional Platt calibration is fitted on an
earlier validation cohort and selected against identity calibration on a later
cohort. The earlier cohort excludes candidates and organizations present later;
exposure ties stay together. If there is insufficient calibration data, identity
calibration remains. The evaluation threshold maximizes validation balanced
accuracy. None of those choices can access test rows.

Validation and test reports include accuracy, balanced accuracy, precision,
recall, F1, confusion matrices, ROC AUC, average precision, log loss, Brier score,
calibration bins, and expected calibration error. Tied scores enter ranking
metrics together. Accuracy, precision and recall include Wilson intervals, whose
independent-observation assumption is disclosed.

Comparators include training prevalence, the raw current compatibility ranking,
and a train-fitted/validation-selected logistic probability mapping of that
compatibility ranking. This third comparator prevents an apparent improvement
caused only by treating an uncalibrated ranking as a probability. Paired loss
comparisons bootstrap complete candidate clusters and complete organization
clusters separately. The reported interval envelopes both results: it is a
dependence sensitivity summary, not a guarantee of joint 95% coverage.

The review screen requires at least 100 rows and 20 examples of each class per
split, at least 20 candidate and organization clusters in each evaluation cohort,
converged training, no organization overlap, observed provenance, and strictly
negative upper interval bounds for both log-loss and Brier differences against
every comparator in validation and test. This screen is a practical minimum,
not a sample-size calculation or a reliability certification. Test outcomes
cannot select parameters. Repeatedly tuning against the same test cohort makes
it a validation cohort; use a new future holdout for the next independent claim.

## Continual improvement and rollback

The one-shot refresh command connects export, incumbent freezing, training and
optional registry promotion. It uses the configured backend environment and
database; it does not create a scheduler or contact a hosted service merely by
being installed. An operator or existing job runner can invoke it repeatedly
with a fresh output directory and newly declared future evaluation cutoffs:

```powershell
.venv/Scripts/python.exe -m scripts.refresh_matching_learning `
  --output .local/matching-refresh/run-001 `
  --train-before 2026-07-01T00:00:00Z `
  --validate-before 2026-09-01T00:00:00Z
```

This command requires the backend dependencies and NumPy 2 or later in the chosen Python
environment. It reads and freezes the current active model before exporting
consented outcomes. `refresh_status.json` records a trained challenger, rejected
evidence, insufficient data, or a sanitized failure. Empty exports and missing
forward-time cohorts preserve the active model and produce no invented accuracy.
Install the operator environment with `pip install -c requirements.lock -e '.[learning]'`.
Portable API inference remains dependency-free and does not import NumPy.
If historical observations exceed the bounded export limit, add an explicitly
declared recent window such as `--observed-since 2026-01-01T00:00:00Z`. This filters
immutable observation creation timestamps before the row limit is applied;
it does not silently truncate the dataset or create labels for pending outcomes.
The window must still contain enough training, validation and test observations
for the declared cutoffs. `refresh_status.json` records the normalized UTC bound,
and the export records it in `export_window.json` beside the unchanged strict
manifest. Input hashes identify the actual selected rows. Omitting the flag
preserves full-history export behavior and its explicit overflow error.
Development, test and staging exports are labeled fictional. Append `--promote`
only in the configured production environment to request promotion after all
observed-outcome evidence checks pass. The backend transaction checks the frozen
incumbent hash, current consent epoch and unused future test cohort, and writes
the versioned model, audit and outbox records together. A race or failed check
leaves the previously active model in place. No active-model file is overwritten.

As new explicit outcomes accumulate, produce a new frozen export and train into
a fresh directory. Never overwrite an earlier artifact. Pass the current active
model when one exists:

```powershell
.venv-research/Scripts/python.exe -m scripts.matching_learning `
  --input .local/matching-outcomes/next/introductions.jsonl `
  --manifest .local/matching-outcomes/next/manifest.json `
  --train-before 2026-10-01T00:00:00Z `
  --validate-before 2026-11-01T00:00:00Z `
  --incumbent .local/matching-models/incumbent/observed_model.json `
  --output .local/matching-models/challenger-002
```

The incumbent must have compatible target/features/horizon, genuine observed
provenance in the same declared dataset population, valid integrity and evidence,
and a source export preceding validation exposure. Its old coefficients,
transforms and calibration stay frozen. Paired comparisons against it become
part of the new review screen. A report can reject a challenger even when a
single headline accuracy metric increases. Retire the current model to restore
deterministic scoring. Earlier registered versions remain as audit history;
activating them again requires a fresh evaluation and new model version.
Ingestion and activation use the backend's versioned, audited, idempotent registry
flow. Training itself has no activation side effect. Weight changes after each click would defeat reproducibility and
amplify exposure feedback, so they are deliberately absent.

`--allow-fictional` is exclusively for labeled software fixtures. It writes
`fictional_model.json` and `fictional_report.json`, always fails review
eligibility, and cannot pass the runtime's normal artifact validator.

## Portable inference contract

Artifacts use schema version 2, kind `reciprocal_logistic_challenger`, and feature
version `reciprocal-structured-v1`. The four `feature_names` have the exact order
shown above. Each feature has a training-fitted transform containing
`imputation_median`, `center`, and `scale` (minimum training scale `0.05`). Its two
interleaved inputs are `(filled_value - center) / scale` and `is_missing`.
The eight `coefficients` follow that order. Compute:

```text
raw = intercept + sum(coefficient[i] * transformed_input[i])
probability = sigmoid(calibration.slope * raw + calibration.intercept)
```

Identity calibration has slope 1 and intercept 0. The artifact includes the
source, horizon, input/manifest hashes, split and selection settings, test cohort
fingerprint, incumbent identity, and review evidence. `model_id` is SHA-256 of
canonical JSON of every other artifact field (`sort_keys=True`, separators
`(',', ':')`, `allow_nan=False`, UTF-8). The shared lightweight runtime validator
checks every emitted artifact before it is written. Production inference needs
no NumPy, pickle, downloaded executable model, or training dependency.

Only four structured inputs may leave little variation after hard eligibility.
Learning cannot recover experience, preferences or outcome evidence that was
never captured. Better features require an explicitly versioned pre-exposure
contract and genuinely observed future evaluation. Mutual-interest prediction
still requires an online controlled evaluation to establish a causal improvement
in introductions or hires while preserving attention ceilings and double opt-in.

Run the focused software checks with:

```powershell
.venv-research/Scripts/python.exe -m unittest discover -s tests/research -p test_matching_learning.py -v
```
