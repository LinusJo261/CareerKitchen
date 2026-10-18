# Offline synthetic matching experiments

For a separate, directly reported employee-satisfaction target, see
[satisfaction research](satisfaction-research.md). Its survey labels and artifacts
are not interchangeable with the synthetic relevance model below.

Run these commands from the CareerKitchen root folder using the research Python,
not the IDE's system Python. No API, frontend or PostgreSQL server is needed.

```bash
.venv-research/bin/python -m pip install -r requirements-research.txt
.venv-research/bin/python -m scripts.matching_research benchmark
.venv-research/bin/python -m scripts.matching_research train
```

Both commands use the three Parquet files already cached by
`scripts/inspect_matching_dataset.py`. The revision is pinned to
`178ab864dcad9910c5670d43e4bdbbb901a11f18`. If that revision is missing locally,
add `--download` once. Downloads go under `.local/matching-research/cache/`.
Alternatively, pass `--data-dir PATH` to a local root containing the dataset's
`data/`, `jobs/` and `matches/` directories. Local overrides are recorded with
SHA-256 file checksums; they are not assumed to match the published revision.

Start with `--max-jobs 10` for a quick run. The default evaluates up to 100 jobs
per partition and trains on up to 100 training jobs. For all jobs, use
`--max-jobs 2500`; this takes longer. `--k` defaults to 30, and `--seed` to 42.

## What the commands do

`benchmark` compares three rankings: the current live scorer's preferred-skill
component (calling its actual helper), required-skill overlap, and an equal blend
of required and preferred coverage. This is not a full replay of live matching:
the dataset cannot supply consent, attention, candidate preferences, compensation,
availability, organization verification or essential-evidence authorization.
Missing preferences make the preferred-only ranking a tie, not a penalty.

`train` additionally fits a small L2-regularized logistic regression using NumPy.
The features are required-skill coverage, preferred-skill coverage, presence of
preferred skills, same seniority and lexical text-token Jaccard similarity. This
text feature is not a semantic embedding. No IDs, relevance lists, label-derived
features, education or outcome explanations enter the feature vector.

The only target is **synthetic relevance**. Listed resumes provide positives.
Negatives are sampled exclusively from resumes below the generator's must-have
skill threshold; they are rule negatives, not real rejections. Threshold-qualified
unlisted pairs are excluded from training. Samples are balanced per job, up to 30
per class. Logits are used for ranking; they are not calibrated probabilities of
mutual interest, interview, offer acceptance or employment.

The training implementation uses stable logistic loss and fixed gradient descent,
without installing a model library in the production backend. The JSON model
contains coefficients/intercept in the declared feature order. It is never loaded
by the API, worker or live matcher.

## Splits and label limitations

The [published generator](https://huggingface.co/datasets/michaelozon/candidate-matching-synthetic/blob/main/Synthetic_Data_Generation%20%281%29.ipynb)
qualifies resumes by at least `ceil(0.6 * unique must-have skills)` matches,
randomly shuffles the qualifying pool, then lists up to 30. Seniority, nice-to-have
skills, industry and text are not used in that label rule. Every supplied positive
is checked against the rule before training; contradictions stop the run.

Consequences:

- Listed Recall@30 measures agreement with an incomplete, randomly selected list.
  It is not real-world matching accuracy. Even an entirely qualifying shortlist
  can miss most listed IDs. If there are Q qualifying candidates and Q >= 30,
  such a ranker's expected listed Recall@30 is approximately 30/Q.
- Threshold-qualified Precision@30 measures whether recommended candidates meet
  the generator's skill threshold. It is not human-reviewed precision.
- A trained model can learn the generator's rule. This dataset cannot establish
  whether seniority, preferred skills or text improve hiring results. A learned
  model need not beat simple required-skill overlap.

Jobs are divided approximately 70/15/15 using a stable hash of structured job
templates (title, seniority, required/preferred skills). Duplicate templates stay
in one split even when their IDs differ. Resumes receive their own content-group
split; duplicate model-visible resumes stay together. Training uses only training
jobs and training resumes. Reports separately evaluate validation jobs and test
jobs against the training-resume pool, plus test jobs against unseen resumes.
The validation-resume partition is reserved, not used for fitting.

Identical description/bullet reuse counts and split sizes appear in diagnostics.
This limits exact-duplicate leakage but cannot eliminate shared role vocabulary
or generator patterns. There are no genuine observation times; this is not a
chronological evaluation. Hyperparameters should be chosen on validation; do not
keep tuning against test scores. Split first, train second, test last.

## Outputs and interpretation

Generated artifacts are local and ignored by Git:

```text
.local/matching-research/
    benchmark_report.json
    train_report.json
    synthetic_relevance_model.json
```

Reports record dataset revision, file hashes, split diagnostics, evaluation pool
sizes, mean metrics, first-job recommendations and limitations. Training reports
also contain coefficients, sample counts and loss values. Compare methods within
the same scenario: the training and unseen candidate pools have different sizes, so
their Recall@30 is not directly comparable.

Run software checks without downloading data:

```bash
.venv-research/bin/python -m unittest discover -s tests/research -v
```

This research never creates real profiles, decisions, consent or employment
outcomes. No live ranking or eligibility rule is changed. Synthetic performance
does not establish reliability certification; prospective first-party evidence is
still needed before any learned model could control introductions.
