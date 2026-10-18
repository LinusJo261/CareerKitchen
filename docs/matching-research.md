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

## Further experiments with Model A

The saved initial run used 100 of 1,733 available training jobs, producing 4,202
balanced pairs. The existing grouped split also contains 404 validation jobs
and 363 test jobs. The separate learning-curve command now compares 25, 100, 500
and all available training jobs without evaluating test jobs or test-resume
candidate pools:

```bash
.venv-research/bin/python -m scripts.matching_learning_curve \
  --output .local/matching-research/learning-curve-1
```

The command uses the same pinned source files and grouping rules as the initial
experiment. A seed-42 hash orders training job templates before looking at
labels. The training sets are nested and keep duplicate templates together;
the actual job count can slightly exceed a requested size to finish a template
group. This differs from the original run's sorted job-ID prefix, so comparisons
with that run's test scores are not controlled training-size comparisons.

At each size, it fits required-skill-only and all-five-feature logistic models
using the fixed L2 grid `0.1, 0.01, 0.001` and 500 gradient steps. Required-only
models keep the existing five-column contract with the other four weights zero.
Pair sampling is unchanged: listed positives, confirmed below-threshold rule
negatives, and no invented negatives for qualifying unlisted resumes. Training
features are calculated once per selected pair and reused across candidates.

Regularization is selected by pooled log loss on a single fixed, balanced sample
of known pairs from **validation jobs and unseen validation resumes**. Those
samples and their fingerprints stay identical at every size. Validation jobs
against the training-resume pool are a separate diagnostic. Recall@30 and
rule-qualified Precision@30 are reported for both pools, alongside required-only
and equal required/preferred-overlap reference rankings. Randomly capped listed
Recall@30 does not select features or regularization. Artificially balanced pair
loss is a synthetic discrimination metric, not a calibrated match probability.

The export uses the largest declared training size, with its feature variant and
regularization selected using validation loss. The resulting candidate has not
received independent final testing. Previously viewed test results are already
exploratory, not a pristine final confirmation. The older `train` command still
evaluates test partitions; use the new command for this validation-only study.

The new output directory contains `protocol.json`, `report.json` and
`experimental_model.json`. It records source revision/file hashes, the fixed
grid, nested size counts, feature choices, validation sampling fingerprints,
ranking metrics and JSON coefficient replay. Output publication is atomic and
refuses existing directories; prior artifacts and live matching are preserved.

The first declared run completed in
`.local/matching-research/learning-curve-1/`. It used all 404 validation jobs;
402 have listed positives inside the 1,500-person unseen-validation resume pool.
That primary pool supplied 3,654 fixed balanced pairs. Each size selected
`l2=0.001` for both feature variants:

| Training jobs | Training pairs | Required-only validation log loss | Five-feature validation log loss | Required-only listed Recall@30 | Five-feature listed Recall@30 |
| --- | --- | --- | --- | --- | --- |
| 25 | 1,066 | 0.07991 | 0.08200 | 22.97% | 22.42% |
| 100 | 4,208 | 0.08033 | 0.08177 | 22.97% | 22.83% |
| 500 | 21,042 | 0.08029 | 0.08245 | 22.97% | 22.40% |
| 1,733 | 73,002 | 0.08059 | 0.08268 | 22.97% | 22.42% |

Lower pair loss is better; higher listed recall is better, subject to the
random-cap limitation. More synthetic training data did not improve validation
rankings in this run. Required-only logistic regression produced exactly the
same ordering as required coverage at every size; its changing coefficient only
changed score margins. All reported learned rankings were 100% qualified under
the generator's threshold, which is not 100% human-reviewed relevance.

The declared largest-size policy exported the 1,733-job required-only model with
`l2=0.001`. Its better loss than the five-feature alternative is evidence about
this synthetic rule, not learned real hiring preferences. It was saved as a
separate candidate and did not replace the previous five-feature artifact.
Test pools were not scored. The 22.97% validation recall uses a different job
and resume pool from earlier test reports and cannot be read as a change from
their reported recall percentages.

Compare required-skill-only logistic regression with the existing five-feature
model before adding text complexity. A BM25 or frozen-embedding challenger can
test retrieval behavior, but this export has heavily reused text: diagnostics
count 9,999 reused resume-bullet rows and 2,260 reused job-description rows.
Do not assume a semantic model supplies new information that the documents lack.
Confirmed near-threshold negatives may help training; threshold-qualified
unlisted resumes must remain unlabeled. More data or tuning is not guaranteed
to help a benchmark whose labels already depend only on a simple skill rule.

Other public data can support separate relevance experiments. The following
sources were inspected as options; none was downloaded into the repository:

| Source | Labels and possible use | Limitations |
| --- | --- | --- |
| [med2425/resume-job-fit-merged-v1](https://huggingface.co/datasets/med2425/resume-job-fit-merged-v1/blob/main/README.md) | 93,733 resume/job pairs, graded Good/Potential/No Fit by Qwen2.5-32B; possible weak supervision for text relevance | Both train and test use model judgments, not hiring outcomes; no explicit license is declared in the inspected card |
| [cnamuangtoun/resume-job-description-fit](https://huggingface.co/datasets/cnamuangtoun/resume-job-description-fit/tree/main) | Approximately 8,000 paired resume/job fit examples | Original collection/annotation provenance is undocumented; [license clarification remains unresolved](https://huggingface.co/datasets/cnamuangtoun/resume-job-description-fit/discussions/3) |
| [Vanetik and Kogan human-ranking benchmark](https://github.com/NataliaVanetik/vacancy-resume-matching-dataset) | 65 anonymized CVs; human job rankings for the first 30 against five vacancies, with senior-HR annotation instructions | Small relevance evaluation set, not a large training corpus or observed hiring success; repository declares GPL-3.0 |

The merged Hugging Face corpus includes the smaller fit corpus, so these cannot
be treated as independent train/test sources without checking overlap. Confirm
source provenance and usage terms before adopting either for training. A new
dataset with text judgments needs its own importer, target declaration,
job/resume/template grouping and evaluation; it is not a drop-in extension of
the current five-feature threshold-label experiment.

The immediate recommendation is to measure the value of the unused current
training jobs, then evaluate richer text features against independent human
rankings. Neither synthetic fit labels nor WFHS satisfaction predictions create
evidence that both a candidate and employer will choose to proceed.

The human-ranking text experiment is documented separately in
[the human benchmark guide](matching-human-benchmark.md). It ranks five jobs
for each CV; it does not replay the full backend matcher or fabricate the
structured skills that the five-feature synthetic model requires.

The next comparison adds a frozen, pinned MiniLM encoder to that same benchmark;
see [the semantic experiment guide](matching-semantic-benchmark.md). It keeps
full document coverage with fixed token windows and leaves pretrained weights,
human annotations and lexical reference methods unchanged.
