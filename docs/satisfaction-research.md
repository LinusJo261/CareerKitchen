# Reported job satisfaction research

For Model B's separate workplace-baseline-to-12-month satisfaction experiment
using Tomo, see [WFHS research](wfhs-research.md). Earlier Leef results remain
available for comparison.
That study-entry experiment does not use the prehire/job-start mapping below.

For the target combining direct employee and manager ratings using the lower
rating, see [joint satisfaction](joint-satisfaction.md). It extends this offline
trainer with paired reports; the employee-only survey run below remains separate.

This is a separate, offline experiment. It does not replace the live matching
algorithm or the synthetic-relevance experiment. No model here can create cards,
grant evidence access, or change consent, double opt-in or attention limits.

The target is **the employee's directly reported satisfaction with an observed
employment spell**, at the first eligible rating in a declared follow-up window.
It is not a composite of tenure, promotion and salary. It does not measure employer
satisfaction, mutual interest, or how a person would have experienced an unchosen
job. Ratings are ordered categories, not invented equally spaced satisfaction
units or a global employability score.

## Run the software demonstration now

From the CareerKitchen root, using the existing research environment:

```bash
.venv-research/bin/python -m scripts.satisfaction_research demo
```

This creates 300 **fictional** rows for software verification only and trains a
demonstration classifier. Its results are deliberately easy and do not establish
survey or hiring performance. Every demo artifact has `fictional_` in its name,
`fictional_data: true`, and `live_execution: false`.

```text
.local/satisfaction-research/fictional-demo/
    fictional_observations.csv
    fictional_mapping.json
    fictional_satisfaction_model.json
    fictional_satisfaction_report.json
```

NumPy is the only training dependency; the current research environment already
has it. On another machine, install `requirements-research.txt` in a separate
virtual environment. No API, PostgreSQL server, frontend or external model API is
required. Generated data/models stay in ignored `.local/` storage.

## Obtain an actual NLSY97 export

A real CSV and its accompanying codebook are required for survey training.
The fictional demonstration never establishes a real evaluation score.

1. Open [NLS Investigator](https://www.nlsinfo.org/investigator). Guest search is
   available; choose NLSY97's main public-use dataset.
2. Select several rounds so a future-time evaluation is possible. Tag respondent
   `PUBID` and satisfaction question `YEMP-101200` for the relevant employer slots,
   matching employer UID, job-start month/year, and interview month/year. Include
   job-stop dates for ended jobs and only documented prehire/start predictors.
3. Download CSV **with reference-number headers**, codebook and tagset. Question
   names can repeat across rounds. Use the actual codebook for every round/slot;
   questionnaire base references are not a safe recipe for exported column IDs.
4. Keep the export and codebook under `.local/satisfaction-research/raw/`. The
   scripts do not read credentials or contact NLS Investigator.

Official instructions: [guest access](https://www.nlsinfo.org/content/access-data-investigator/investigator-user-guide/getting-started),
[custom downloads](https://nlsinfo.org/content/access-data-investigator/investigator-user-guide/customized-data-download).

The [Round 12 questionnaire](https://www.nlsinfo.org/sites/default/files/attachments/121129/nlsy97r12emp.html)
defines satisfaction codes as 1 likes very much, 2 likes fairly well, 3 OK,
4 dislikes somewhat, 5 dislikes very much. The example mapping explicitly reverses
their order for model class indices: 0 worst through 4 best. Validate these
meanings against the codebooks for every selected wave rather than assuming
all survey instruments use identical codes.

[NLS missing-response codes](https://www.nlsinfo.org/content/cohorts/nlsy97/using-and-understanding-the-data/item-nonresponse-interview-timings)
`-1` through `-5` represent refusal, don't know, invalid skip, valid skip and
noninterview. Missing labels are excluded and counted, never treated as low
satisfaction. Missing predictor values have training-only imputation/indicators.

## Prepare the export without guessing timing

Create an empty input and mapping template:

```bash
.venv-research/bin/python -m scripts.satisfaction_research init
```

This writes `.local/satisfaction-research/input/observations.csv` and
`mapping.json`. It refuses to overwrite existing templates.

The trainer expects **long-format observations**, one row per respondent,
employment spell and rating. The converter reads the selected reference numbers
from the downloaded codebook and performs exact survey-year/employer-slot joins:

```bash
.venv-research/bin/python -m scripts.prepare_nls_satisfaction \
  --input .local/satisfaction-research/raw/career_kitchen_satisfaction/career_kitchen_satisfaction.csv \
  --codebook .local/satisfaction-research/raw/career_kitchen_satisfaction/career_kitchen_satisfaction.cdb
```

It writes `observations.csv`, `mapping.json` and `preparation_report.json` under
`.local/satisfaction-research/prepared/`; raw files remain unchanged. Preparation
reports field coverage by survey year and counts all exclusions. Only valid labels
with same-round identity/timing and a 3–24 month follow-up are included. Missing
later dates are never inferred from the survey year or copied from an earlier
employer record.

The initial real-data predictor is **`weekly_hours_at_start`**, coalescing exact
`YEMP-23901` and `YEMP-34402` branches when observed and consistent. `H` variants
measure hours at home and are excluded. Missing/invalid hours are excluded from
this single-feature experiment. These are retrospectively reported start/resume
conditions, not contractual offered hours. `feature_as_of` here denotes the
job-start reference period, not the later survey collection date. This distinction
limits any claim of prospective recommendation usefulness.

To reproduce the first survey run with respondent-disjoint, forward-time splits:

```bash
.venv-research/bin/python -m scripts.satisfaction_research train \
  --input .local/satisfaction-research/prepared/observations.csv \
  --mapping .local/satisfaction-research/prepared/mapping.json \
  --train-before 2013-01 --validate-before 2019-01 \
  --output .local/satisfaction-research/survey-run
```

The supplied export covers survey years 1997–2023, with latest-round interviews
extending into 2024. The first run prepared 50,344 observations and retained
50,303 spells after duplicate-rating selection. Training used 27,311 observations;
validation used 725 and test used 533, with the remaining rows outside the
declared group/time cohorts. Test exact-category accuracy was 46.34%, equal to
the training-majority-category baseline. This establishes no predictive advantage
in exact-category accuracy, and no validated matching performance. Full metrics,
input hashes and settings are in the ignored local survey report.

The example template's column names below are canonical prepared-data names, not
invented NLS variable IDs. Its optional multi-feature setup is distinct from the
converter's single-feature hours-at-start mapping.

| Column | Meaning |
| --- | --- |
| `person_id` | Respondent's pseudonymous ID; never a predictor |
| `employer_id` | Employer UID within that respondent's history; never a predictor |
| `job_started_at` | Actual employment-spell start month, `YYYY-MM` |
| `feature_as_of` | Month by which all selected predictors describe known prehire/start conditions |
| `rating_reference_at` | Month the rating refers to: interview month for ongoing work; documented stop/reference month for ended work |
| `rating_observed_at` | Interview month when that rating became available |
| `satisfaction` | Raw response code, mapped explicitly by the codebook |

The initial template includes prior experience, offered weekly hours and
employment type as example predictors. Remove any that cannot be reconstructed
honestly from the export; they are not assertions that NLS has those exact
columns. Other allowed predictors are offered hourly pay, role family, work mode,
industry at start and schedule at start. Demographics, identity, final tenure,
promotions, later wages and the label cannot be configured as predictors.

The example source release is deliberately a placeholder: validation refuses it
until replaced with the actual release/waves. Review and adapt label mappings,
selected feature columns and per-feature timing declarations. Start/current/stop
variables are not interchangeable. A timestamp or a declaration cannot prove a
field really was available at hiring; the codebook and extraction logic must.

Public interview timing is [month/year](https://www.nlsinfo.org/content/cohorts/nlsy97/intro-to-the-sample/interview-methods),
so this pipeline compares months rather than fabricating exact days. Fields dated
within the same month need a documented start-of-job meaning; same-month ordering
cannot be inferred. Historical pay comparisons also require consistent currency,
period and price-level treatment in preparation, rather than silently mixing
nominal wages across decades.

An employer UID alone is not a spell key: someone can leave and return. The
trainer uses respondent + employer + start month, keeps the earliest eligible
observed rating, and counts later ratings excluded from the same spell. If two
distinct spells cannot be distinguished at month resolution, resolve that
ambiguity before preparing input. See [NLS tenure documentation](https://www.nlsinfo.org/content/cohorts/nlsy97/topical-guide/employment/tenure).

The declared default follow-up is **3 to 24 months after starting**, using the
rating reference month. This is an adjustable study choice, not a native survey
guarantee or a fixed 12-month outcome. The question concerns current or ended
jobs; a late interview must not be mislabeled as satisfaction at hiring.

## Validate, then train on real observations

After preparation and codebook review:

```bash
.venv-research/bin/python -m scripts.satisfaction_research validate \
  --input .local/satisfaction-research/input/observations.csv \
  --mapping .local/satisfaction-research/input/mapping.json
```

Choose date boundaries that match the exported rounds. The following cutoffs are
an example, not a claim that an unsupplied export spans these years:

```bash
.venv-research/bin/python -m scripts.satisfaction_research train \
  --input .local/satisfaction-research/input/observations.csv \
  --mapping .local/satisfaction-research/input/mapping.json \
  --train-before 2005-01 --validate-before 2015-01
```

The split combines respondent hash groups with forward time:

- Train: training-group people, outcomes known before the first cutoff.
- Validation: separate people, jobs starting at/after the first cutoff, outcomes
  known before the second cutoff.
- Test: separate people, jobs starting at/after the second cutoff.

Consequently some rows are deliberately unused. Reports count them and stop if
any split is empty. The same respondent's repeated jobs never leak across folds.
Select cutoffs and features using the study design and validation results, then
freeze them before final test evaluation.

The predictor is a small L2-regularized multinomial logistic classifier. Scaling,
numeric medians and category vocabularies are fitted on training only. Unseen
categories get an unknown indicator; values outside training numeric ranges are
clipped. At least two outcome categories must occur in training.

The report compares against predicting the most frequent training category, with
training frequencies used for the baseline distribution. It includes exact
category accuracy, category-step MAE, within-one-category accuracy, log loss,
multiclass Brier score and a confusion matrix. The category order matters to the
distance metrics; equal steps do not mean equal satisfaction intervals. Model
probabilities are uncalibrated and cannot be interpreted as validated hiring
probabilities. Missing/absent classes and survey selection can limit results.

Real-input artifacts are named `survey_satisfaction_model.json` and
`survey_satisfaction_report.json`. They contain encoder statistics, feature/class
order, coefficients, input/mapping hashes, split settings and limitations. No raw
respondent IDs or per-person predictions are exported into the reports/models.
The current experiment does not apply survey weights, estimate population effects
or claim causal or fairness certification.

## Verify implementation

```bash
.venv-research/bin/python -m unittest discover -s tests/research -v
```

All included fixtures are explicitly fictional. Real export extraction, field
alignment, population representativeness and prospective product validation remain
external checks. A satisfaction model can be investigated in read-only research;
activating it in the live matching path is not part of this implementation.
