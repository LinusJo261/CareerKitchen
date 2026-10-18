# WFHS employee satisfaction experiment

This is a separate offline research experiment using the locally downloaded
**Work, Family, and Health Study, ICPSR 36158 v2**. It does not replace the NLSY97
experiment, join survey respondents to synthetic resumes, combine Model A and
Model B, or change backend matching.

**Model B uses Tomo (DS0001) only.** Preparation and training default to Tomo.
The selected model and evaluation are saved under
`.local/wfhs-research/model-b-tomo/tomo/`. Leef files and the earlier two-dataset
run remain available as historical comparison data, outside the selected model.

The source files and model artifacts remain under ignored `.local/` storage.
The supplied ICPSR terms limit the data to research/statistical purposes and
restrict redistribution. Preserve those terms and the accompanying documentation.
This experiment does not identify study participants or export raw survey data.

## Source files

Keep the downloaded directory intact:

```text
.local/satisfaction-research/raw/WFHS_Data/
    DS0001/36158-0001-Data.tsv    # Tomo, IT division
    DS0002/36158-0002-Data.tsv    # Optional Leef comparison; not needed for Model B
    36158-Codebook.pdf
    36158-User_guide.pdf
    TermsOfUse.html
```

The actual TSV files contain 3,684 participant-wave rows and 112 columns for
Tomo, and 5,509 participant-wave rows and 115 columns for Leef. These are repeated
observations, not that many independent people or hiring decisions.

Official sources: [study and citation](https://www.icpsr.umich.edu/web/DSDR/studies/36158),
[variable catalog](https://www.icpsr.umich.edu/web/DSDR/studies/36158/variables),
and the supplied public-use codebook, sections 1, 3, 4, 7, 16 and 20.

## Prediction task and inputs

Predict an **existing employee's satisfaction at the nominal 12-month follow-up**
from workplace conditions recorded at study baseline. Baseline is not job start.
There are no invented job-start dates or prehire timing declarations.

The target `SCWM_JSAT` is the mean of three reverse-coded items, `WM_JSAT1R`,
`WM_JSAT2R`, and `WM_JSAT3R`. It ranges from 1 to 5, with higher values indicating
greater satisfaction. Its fractional values are preserved and checked against
the three items. They are not rounded into the five NLSY97 response categories.
Prediction errors describe numerical questionnaire-scale units, not measured
increments in satisfaction utility or a percentage chance of matching.

The six inputs are taken only from `WAVE=1`:

| Feature | Source | Meaning |
| --- | --- | --- |
| `control_over_work_hours` | `SCWM_CWH` | Control over work time |
| `family_supportive_supervisor` | `SCWM_FSSB` | Family-supportive supervisor behavior |
| `decision_authority` | `SCWM_JSTRDA` | Decision authority at work |
| `psychological_job_demands` | `SCWM_JSTRPJD` | Psychological job demands |
| `hours_worked_last_week` | `WM_HPQ1` | Actual hours in the previous calendar week |
| `hours_expected_by_manager` | `WM_HPQ2R` | Corrected baseline expected weekly hours |

`WM_HPQ2R` is the documented baseline correction of `WM_HPQ2`. The pipeline does
not substitute missing expected hours with actual hours. Non-imputed scales are
used; feature medians and scaling are fitted on the training partition only.
Missing indicators are retained. Only documented missing codes for these
selected columns are accepted; unexpected values fail validation.

`ADMINLINK` and `WAVE` supply the exact longitudinal join. Only employee
respondents (`EMPLOYEE=1`, `MANAGER=0`) at baseline and follow-up are included.
Tomo baseline records with `EXCLUDE=1` (not invited) or `2` (not randomized) are
omitted. Missing follow-ups or satisfaction ratings are counted and excluded,
never labeled dissatisfaction. One pair is retained per employee. Baseline
satisfaction must also be present so the same cohort can be compared with a
persistence baseline; it is not a feature of the workplace-condition model.

Manager respondents' satisfaction with their own jobs is not a manager rating of
an individual hire. No joint satisfaction labels are created here.

## Prepare, train, and evaluate

From the repository root, use the existing research Python. No additional
dependencies beyond the research environment's NumPy are required:

```bash
.venv-research/bin/python -m scripts.wfhs_research prepare \
  --output .local/wfhs-research/prepared-tomo-1

.venv-research/bin/python -m scripts.wfhs_research train \
  --output .local/wfhs-research/model-b-tomo
```

Omitting `--dataset` selects only Tomo; the Leef TSV is never read in this mode.
`--dataset tomo` makes the same choice explicitly. `--dataset leef` and
`--dataset both` are available for separate comparison experiments.
`--raw-dir PATH` supports a different location for the same documented export structure.
Output directories must be new. Validation/training failures publish no partial
bundle; source files and older runs are preserved.

Each dataset is modeled separately. Baseline study groups (`STUDYGROUP`) for
Tomo and baseline facilities (`LF_CENTERID`) for Leef are assigned by a stable
seed-42 hash to approximately 70/15/15 training, validation and test groups.
Entire baseline clusters stay together; participants do not cross partitions.
Unequal cluster sizes mean the participant proportions need not be 70/15/15.
The split is not a holdout of later calendar cohorts or new employers.

A small ridge regression models the fractional scale, with an unpenalized
intercept and predictions clipped to 1–5. A fixed penalty grid of
`0, 0.001, 0.01, 0.1, 1` is selected by validation RMSE. Test results do not choose
the penalty. The selected model remains fitted on the training partition.

The report compares validation/test **MAE, RMSE and R-squared** with:

- A constant equal to the training-set mean satisfaction.
- A constant equal to the training-set median satisfaction.
- Each employee's baseline satisfaction, carried forward unchanged.

It also reports model results separately for intervention and control conditions.
Condition is not a predictor. This remains an observational prediction analysis
within a randomized workplace study, not an estimate of intervention effects.
No classification accuracy or calibrated matching probability is reported.

Each output dataset directory contains `observations.csv`,
`preparation_report.json`, and, for training, `model.json` and `report.json`.
The root `manifest.json` records source documentation hashes and the run settings;
dataset hashes are retained in preparation/model reports. Reports contain
aggregate counts and metrics, not participant IDs. Prepared observation files
remain private local research data.

## Historical two-dataset comparison

The uploaded files produced 679 eligible Tomo employees and 1,083 Leef employees.
The default fixed split and validation-selected penalty produced these results
in `.local/wfhs-research/run-1/`:

| Dataset | Train / validation / test people | Selected penalty | Model test MAE | Training-mean MAE | Training-median MAE | Persistence MAE |
| --- | --- | --- | --- | --- | --- | --- |
| Tomo | 526 / 99 / 54 | 0.1 | 0.616 | 0.617 | 0.617 | 0.506 |
| Leef | 614 / 149 / 320 | 0 | 0.479 | 0.501 | 0.470 | 0.449 |

Lower errors are better. Tomo shows essentially no MAE advantage over a constant
prediction. Leef improves on the training mean but does not beat the median or
persistence on MAE. On the predeclared selection metric, RMSE, Tomo is 0.818
versus 0.831 for the training mean and 0.726 for persistence; Leef is 0.611 versus
0.648 for the training mean and 0.651 for persistence. Leef's model therefore
reduces larger errors even though its typical absolute error is higher than
those stronger MAE baselines. Test R-squared is -0.018 for Tomo and 0.108 for Leef.
These are descriptive results, not statistical evidence of a reliable improvement.
The saved encoders and coefficients replayed the test metrics without refitting.
The subsequent Tomo-only Model B bundle preserves the same Tomo data, fixed split,
penalty and results; this dataset selection does not establish an improvement in
prediction performance.

## Interpretation

Even good prediction on these held-out groups would not show that the model can
rank unchosen jobs, predict employer satisfaction, or generalize to CareerKitchen
users. Later supervisor experience and workload are not automatically known when
recommending a job. Baseline satisfaction is also unavailable for an unstarted
job, so the persistence comparator is a research benchmark, not a proposed
matching input.

Attrition, self-reported conditions, the intervention, shared workplace effects
and the two-employer sample limit interpretation. The small Tomo test partition
is particularly uncertain. Do not compare raw WFHS regression metrics with the
NLSY97 five-category classification accuracy; the targets and populations differ.

For the chosen lower employee/direct-manager satisfaction target, use the
separate [paired-report pipeline](joint-satisfaction.md). A WFHS prediction is
not a replacement for either direct report.

## Tomo feature and algorithm comparison

The separate comparison command investigates the existing-employee forecasting
task using only the original training and validation groups. It never evaluates
the previously inspected test set and never replaces the selected Model B.

Install `requirements-research.txt` in the research environment to add
scikit-learn, then run from the repository root:

```bash
.venv-research/bin/python -m pip install -r requirements-research.txt
.venv-research/bin/python -m scripts.wfhs_comparison \
  --output .local/wfhs-research/tomo-comparison-1
```

The importer freezes the original seed-42 test-group allocation and excludes
those groups before parsing satisfaction values. The actual export supplies
625 usable development employees across 50 work groups. There are 64 eligible
baseline employees in reserved groups; this includes people without the matched
12-month observation, so it differs from the earlier 54-person test count.
Leef is not read.

Two feature variants are compared: the original six baseline conditions, and
those conditions plus four prespecified interactions:

| Interaction | Definition |
| --- | --- |
| `hours_gap` | Recent actual hours minus usual manager-expected hours |
| `absolute_hours_gap` | Absolute value of that hours gap |
| `demands_by_low_control` | Normalized demands multiplied by low work-hour control |
| `demands_by_low_support` | Normalized demands multiplied by low family-supportive supervisor behavior |

The last two normalize their original 1–5 scales to 0–1 before multiplying.
Missing inputs propagate to missing interactions; imputation is fitted within
each training fold. The hours comparison concerns different reference periods
and is a workload proxy, not evidence of a candidate's preferences. No current
or future satisfaction response, outcome item, ID, study condition, manager-hire
rating, or invented preference becomes a model feature.

The fixed grid has 14 candidates:

- Ridge regression at the existing five penalties, for each feature variant.
- Gradient boosting with depth 1 or 2, for each feature variant, with 100 trees,
  learning rate 0.03 and minimum leaf size 20. Internal early stopping is disabled
  so it cannot introduce an ungrouped validation split.

Five outer group folds estimate performance. Within each outer training fold,
three inner group folds choose parameters by **RMSE**, the predeclared default
metric used by the earlier experiment. Every fit learns its own imputation and
scaling using only its training data. `--metric mae` is available for a separate,
declared objective; do not switch objectives or seeds to obtain a better-looking
published test result.

Reports include separately tuned ridge/boosting and baseline/interaction
strategies, the procedure that chooses among all 14 candidates inside each
outer fold, and a refitted version of the original ridge recipe (`l2=0.1`).
The original saved model is never scored on development participants it already
trained on. Each outer fold also supplies its own training mean/median reference.
Metrics pool out-of-fold predictions for all employees rather than silently
averaging fold R-squared or RMSE values.

Paired whole-group bootstrap intervals describe error differences versus the
refitted original ridge recipe. They are conditional on the fixed out-of-fold
predictions and exclude full refitting/selection uncertainty. They are not a
reliability certification. The development data have already informed research,
so even nested validation is exploratory; a fresh cohort is needed for final
confirmation.

After evaluation, grouped development-only validation chooses a candidate to fit
on all 625 development observations. `experimental_model.json` stores its encoder
and numerical ridge/tree representation, with no pickle or joblib loading. Replay
is checked against the fitted estimator. Its independently evaluated performance
remains unknown: the nested results describe the selection procedure, not that
particular final fit.

The new directory also contains `protocol.json` and `report.json`, recording the
fixed grid, metric, fold counts, group hashes, source/document hashes, versions,
seed, baselines, uncertainty limits and selection results. Existing active models
and previous reports are preserved. Preparation/comparison failures publish no
partial output bundle.

Model A remains unchanged by this experiment: recruiter judgments and linked real
candidate–job outcomes still need to be collected rather than fabricated.

### First comparison results

The declared comparison completed in `.local/wfhs-research/tomo-comparison-1/`
using 625 employees, 50 work groups, five outer folds, three inner folds and
1,000 paired cluster resamples. These pooled development-fold results share
the same observations and validation boundaries:

| Procedure | MAE | RMSE | R-squared |
| --- | --- | --- | --- |
| Original ridge recipe, refitted per fold | 0.547 | 0.740 | 0.068 |
| Tuned ridge, original features | 0.545 | 0.724 | 0.106 |
| Tuned ridge, added interactions | 0.552 | 0.735 | 0.079 |
| Tuned boosting, original features | 0.539 | 0.717 | 0.124 |
| Tuned boosting, added interactions | 0.543 | 0.722 | 0.112 |
| Nested selection across all candidates | 0.543 | 0.721 | 0.115 |
| Fold training mean | 0.559 | 0.769 | -0.008 |
| Fold training median | 0.549 | 0.766 | -0.000 |
| Baseline satisfaction carried forward | 0.478 | 0.706 | 0.150 |

Lower MAE/RMSE is better. Boosting with the original features produced the lowest
observed error among the four learned strategies. Adding the four interactions
did not improve either family's pooled metrics. The across-candidate selection
procedure reduced RMSE by about 2.6% versus the original ridge recipe; its MAE
reduction was only 0.005 scale points. Its conditional 95% cluster-bootstrap
interval for the RMSE difference was [-0.034, -0.004], whereas the MAE difference
interval [-0.018, 0.010] included zero. These exploratory, conditional intervals
do not establish improvement on fresh data or include full fitting uncertainty.

The development-only final selection chose depth-2 boosting with the original
six features, 100 trees, learning rate 0.03 and minimum leaf size 20. That
candidate was fitted on the 625 development employees and saved separately in
`experimental_model.json`; the table is not an independent evaluation of this
final fit. The original test groups were excluded, and the existing selected
Model B artifact was preserved unchanged. Do not compare these numbers directly
with the historical 54-person test metrics, which used different observations.

The persistence reference still outperformed every learned procedure in this
run. Further algorithm tuning alone has not established a stronger satisfaction
forecast, and none of these results measures candidate–job matching quality.

### Random forest comparison

The optional `--include-random-forest` extension uses protocol
`tomo-forest-nested-groups-v2`. It retains the original 14 candidates and adds
eight random forest configurations: both feature variants, maximum depth 3 or
6, and minimum leaf size 5 or 20. Each forest has 200 trees, uses all encoded
features at each split, and averages trees fitted to bootstrap samples. The
seed is fixed, fitting uses one thread, and out-of-bag scoring is disabled;
the grouped validation procedure supplies the evaluation.
See the [scikit-learn random forest reference](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestRegressor.html).

Run from the repository root with the existing research environment:

```bash
.venv-research/bin/python -m scripts.wfhs_comparison \
  --include-random-forest \
  --output .local/wfhs-research/tomo-comparison-forest-1
```

This uses the same 625 employees, original reserved-test exclusion, group folds,
seed, RMSE objective, fold-local preprocessing and reference procedures. It adds
separately tuned forest strategies and lets the nested selector consider all
22 candidates. The default command without the flag still runs the original
14-candidate protocol. Existing output directories cannot be overwritten.

This extension was chosen after viewing the earlier development results, so
it remains exploratory even with nested group validation. A lower error on
these reused development groups does not establish superiority on a fresh cohort.
Forest artifacts use validated primitive JSON trees with mean aggregation,
with the same employee-satisfaction target and offline-only contract. Model A,
the selected Model B artifact, and live matching are unaffected.

The first forest extension completed in
`.local/wfhs-research/tomo-comparison-forest-1/`. All original strategy metrics
and outer group hashes exactly match the earlier comparison:

| Procedure | MAE | RMSE | R-squared |
| --- | --- | --- | --- |
| Original ridge recipe, refitted per fold | 0.547 | 0.740 | 0.068 |
| Tuned ridge, original features | 0.545 | 0.724 | 0.106 |
| Tuned boosting, original features | 0.539 | 0.717 | 0.124 |
| Tuned forest, original features | 0.539 | 0.719 | 0.118 |
| Tuned forest, added interactions | 0.540 | 0.721 | 0.115 |
| Nested selection across all 22 candidates | 0.539 | 0.719 | 0.118 |
| Baseline satisfaction carried forward | 0.478 | 0.706 | 0.150 |

Boosting retains the lowest observed RMSE among the learned family/feature
strategies; the original-feature forest is close, at 0.71946 versus 0.71711.
Forest MAE is slightly lower, at 0.53885 versus 0.53912, but RMSE remains the
declared selection objective. This does not establish a general winner between
the families. Added interactions did not improve the forest either, and the
persistence reference remains stronger on both error metrics.

Development-only final selection chose a depth-3 forest with minimum leaf size
20 and the original six features; its 200-tree fit on all 625 development rows
is saved in the new `experimental_model.json`. This choice uses development
validation inside the declared protocol, not the pooled outer metrics in the
table. Those metrics evaluate selection procedures; independent performance of
the final artifact remains unknown. Both the earlier boosting artifact and the
selected Model B were preserved, and saved-artifact replay was verified.

Run focused software checks with:

```bash
.venv-research/bin/python -m unittest tests.research.test_wfhs_model \
  tests.research.test_wfhs_pipeline tests.research.test_wfhs_comparison_features \
  tests.research.test_wfhs_comparison_models tests.research.test_wfhs_comparison -v
```

## Expanded baseline feature comparison

`--expand-baseline-features` selects protocol
`tomo-expanded-baseline-nested-groups-v3`. It imports three additional Tomo
baseline scales using the supplied codebook's definitions:

| Feature | Source | Domain and direction |
| --- | --- | --- |
| Work-to-family conflict | `SCWM_WTFC` | 1–5; higher means more conflict |
| Emotional burnout | `SCWM_BURN` | 1–7; higher means more burnout |
| Work-family climate | `SCWM_OCLI` | 1–5; higher means less pressure to sacrifice personal/family life |

Blank and documented `-8` values remain missing. Two development employees
are missing conflict, two are missing burnout and three are missing climate.
Their rows remain in the same 625-person, 50-group cohort; each fit learns its
own imputation from training rows only. Extra fields are read only from wave 1,
never from the follow-up observation. Original test groups are skipped before
parsing these extra values or satisfaction outcomes.

The comparison separates these input sets rather than attributing any gain
to all additions together:

| Variant | Inputs |
| --- | --- |
| `baseline` | Original six conditions |
| `expanded` | Original six plus the three new workplace scales |
| `baseline_with_satisfaction` | Original six plus baseline satisfaction |
| `expanded_with_satisfaction` | All nine conditions plus baseline satisfaction |

The earlier four-interaction variant remains as a reference. Baseline
satisfaction is explicitly allowed only in the two named satisfaction variants;
it is measured at study entry, before the wave-3 target. It is not a prehire
feature and does not predict a manager's satisfaction with a hire. The importer
keeps it separate; the comparison supplies a validated ten-field context and
each model selects only its declared subset. Targets, IDs and unrecognized
fields cannot silently become predictors.

Run from the repository root:

```bash
.venv-research/bin/python -m scripts.wfhs_comparison \
  --include-random-forest --expand-baseline-features \
  --output .local/wfhs-research/tomo-comparison-expanded-1
```

With forests enabled this declares 55 candidates, using the same ridge,
boosting and forest parameter grids as before for each input variant. Without
forests it has 35 candidates. Selection remains RMSE, with seed 42, five outer
group folds, three inner group folds and 1,000 conditional cluster resamples.
All variants are evaluated on the same rows and outer folds. The original
six-input strategies remain separately reported, and carry-forward satisfaction
remains a reference. No original test metric or active-model replacement occurs.

These features were chosen after earlier development comparisons were viewed.
Any improvement is exploratory existing-employee forecasting performance; the
final refit still needs independent evaluation on fresh data.

The declared expanded run completed in
`.local/wfhs-research/tomo-comparison-expanded-1/`. The cohort, group hashes and
all unchanged strategy metrics exactly match the earlier forest comparison.
The following are pooled outer-fold results on the same 625 employees:

| Inputs | Algorithm | MAE | RMSE | R-squared |
| --- | --- | --- | --- | --- |
| Original six | Tuned boosting | 0.539 | 0.717 | 0.124 |
| Nine workplace conditions | Tuned ridge | 0.538 | 0.706 | 0.151 |
| Nine workplace conditions | Tuned boosting | 0.536 | 0.706 | 0.152 |
| Nine workplace conditions | Tuned forest | 0.533 | 0.703 | 0.159 |
| Original six + baseline satisfaction | Tuned ridge | 0.479 | 0.632 | 0.319 |
| Original six + baseline satisfaction | Tuned boosting | 0.476 | 0.626 | 0.332 |
| Original six + baseline satisfaction | Tuned forest | 0.472 | 0.625 | 0.334 |
| Nine conditions + baseline satisfaction | Tuned ridge | 0.484 | 0.634 | 0.316 |
| Nine conditions + baseline satisfaction | Tuned boosting | 0.479 | 0.629 | 0.327 |
| Nine conditions + baseline satisfaction | Tuned forest | 0.473 | 0.629 | 0.325 |
| Nested selection across all 55 candidates | Selected inside each outer training fold | 0.474 | 0.627 | 0.331 |
| Baseline satisfaction carried forward | No fitted model | 0.478 | 0.706 | 0.150 |

Added workplace scales modestly reduced observed RMSE without baseline
satisfaction, but did not beat persistence on MAE. Including the earlier
satisfaction report reduced larger prediction errors further; the seven-input
forest had the lowest observed family/variant RMSE. Adding all three conditions
on top of those seven inputs did not improve pooled results. These comparisons
do not turn satisfaction into a prehire feature or an employment-match label.

Final development-only model selection chose depth-2 boosting with the nine
conditions plus baseline satisfaction, 100 trees, learning rate 0.03 and minimum
leaf size 20. That final fit is stored separately in `experimental_model.json`.
It was chosen using development validation, without selecting on outer metrics;
the table describes held-out prediction procedures, not independent performance
of this particular refit. JSON replay of the new and older candidates was
verified, and the selected Model B artifact remains byte-for-byte unchanged.

Additional importer checks:

```bash
.venv-research/bin/python -m unittest tests.research.test_wfhs_expanded_inputs -v
```

## Fitted baseline-satisfaction-only control

The opt-in `--include-satisfaction-only` extension uses protocol
`tomo-satisfaction-only-nested-groups-v4` and requires
`--expand-baseline-features`. It adds the `satisfaction_only` variant, whose
single raw predictor is the employee's wave-1 satisfaction response. This is a
fitted forecast of wave-3 employee satisfaction, with the same target as the
condition models. Carrying the earlier response forward unchanged remains a
separate reference: fitting can learn regression toward the training mean and
other relationships that the carry-forward reference cannot.

Run from the repository root:

```bash
.venv-research/bin/python -m scripts.wfhs_comparison \
  --include-random-forest --expand-baseline-features \
  --include-satisfaction-only \
  --output .local/wfhs-research/tomo-comparison-satisfaction-only-1
```

The declared grid retains the previous 55 candidates as an exact prefix and
adds the same five ridge, two boosting and four forest configurations for the
one-input variant, for 66 candidates total. Without forests there are 42.
Protocol v4 requires RMSE selection; its actual run uses seed 42, five outer
work-group folds, three inner folds and 1,000 conditional cluster resamples.
All variants use the same 625 development employees and 50 work groups as the
earlier experiments. Original seed-42 test groups remain excluded before
numeric outcome parsing. No earlier test metrics enter model selection.

The full ten-field context is validated, but each satisfaction-only estimator
and its encoder receive only `baseline_satisfaction`. The other nine fields,
including their missingness, cannot affect its learned state or predictions.
IDs, follow-up outcomes, partial contexts and undocumented fields are rejected.
Imputation, scaling and missing indicators are fitted on each training fold;
the one raw input therefore has its normal scaled and missing-indicator encoded
columns. Existing six-input and expanded JSON artifacts retain their contracts.

The report contains the pooled held-out metrics for all three satisfaction-only
families alongside the corresponding seven- and ten-input models. Its
`baseline_satisfaction_ablation` section includes paired work-group bootstrap
error differences, using the fitted one-input procedure of the same family as
the reference. Negative differences favor the added conditions. These intervals
are descriptive, conditional on the fixed out-of-fold predictions; they exclude
full refitting and model-selection uncertainty. The additional ablation was
chosen after viewing earlier development results, so fresh data is still needed
to establish a reliable improvement.

This comparison tests how much information workplace conditions add beyond an
existing employee's prior satisfaction. It cannot establish performance for an
unstarted job, employer satisfaction, a joint-satisfaction target, or mutual
matching. The final selected candidate is saved separately and never promoted
to live matching or over the original selected Model B.

The first declared v4 run completed in
`.local/wfhs-research/tomo-comparison-satisfaction-only-1/`. Its cohort hash,
outer training/validation group hashes, previous 55 candidates and every
unchanged procedure's metrics exactly match the earlier expanded comparison.
Pooled out-of-fold RMSE on the same 625 employees was:

| Algorithm | Satisfaction only, one input | Six conditions + satisfaction, seven inputs | Nine conditions + satisfaction, ten inputs |
| --- | --- | --- | --- |
| Tuned ridge | 0.629 | 0.632 | 0.634 |
| Tuned boosting | 0.632 | 0.626 | 0.629 |
| Tuned forest | 0.631 | 0.625 | 0.629 |

Carrying baseline satisfaction forward unchanged has RMSE 0.706. Fitting a
one-input ridge forecast reduces that error to 0.628722, with MAE 0.471015 and
R-squared 0.326610. Thus most of the previously observed gain from including
baseline satisfaction is already available from fitting that response alone.
The seven-input forest retains the lowest observed family/variant RMSE,
0.625455, but its advantage over the same-family one-input forest is only
0.005178 RMSE. The conditional 95% work-group interval for that difference is
[-0.014076, 0.004756]; all six RMSE intervals for adding conditions include zero.
These exploratory results give little evidence of additional predictive value
from workplace conditions beyond the prior response on this cohort. They do not
establish that the conditions are uninformative on new data.

The nested all-candidate selector chose satisfaction-only ridge in each outer
training fold (four selected zero penalty, one selected 0.001), yielding pooled
RMSE 0.628722. Its all-development final selection instead chose depth-2 boosting
with nine conditions plus baseline satisfaction, the same candidate chosen by
v3. This is expected to be possible: the final development validation and each
outer training fold contain different training subsets. The separately saved
final fit has not been independently evaluated; the lowest pooled error is not
used to override the declared selection procedure. Active Model B remains
byte-for-byte unchanged, and no original reserved test outcomes were evaluated.
