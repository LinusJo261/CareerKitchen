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

Run focused software checks with:

```bash
.venv-research/bin/python -m unittest tests.research.test_wfhs_model \
  tests.research.test_wfhs_pipeline -v
```
