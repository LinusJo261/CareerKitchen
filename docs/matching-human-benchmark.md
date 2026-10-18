# Human-ranking lexical benchmark

This offline experiment checks whether fixed text retrieval methods agree with
human job rankings. It does not replace or retrain Model A, issue introductions,
or change application matching.

The source is [Vanetik and Kogan's public benchmark](https://github.com/NataliaVanetik/vacancy-resume-matching-dataset),
pinned to commit `7ee8f043c6e31ee94cb67f5e60b069901b533adf`. Its repository
provides a GPL-3.0 license and requests citation of:

Vanetik, Natalia, and Genady Kogan. 2023. *Job Vacancy Ranking with Sentence
Embeddings, Keywords, and Named Entities*. Information 14(8), 468.
[doi:10.3390/info14080468](https://doi.org/10.3390/info14080468).

The pinned source archive, including its license, README, annotation instructions,
and original files, stays under ignored `.local/matching-human-benchmark/source/`.
Raw documents, individual rankings, and document text are not checked into this
project. The source archive SHA256 is
`a30003477335398662c853125df17eae5493f72229225ab8e4becc7dbf7b0bba`.
The research script records a separate SHA256 for every source file.

## Annotation meaning and data checks

The repository contains 65 anonymized software-developer CVs, five vacancies, and
two independent human orderings for each of the first 30 CVs. The authors' paper
describes annotators with computer-science backgrounds who received guidance
from a senior HR manager. These are human judgments about relevance, rather than
observed applications, mutual interest, offers, or hiring success.

**Each CV is a query, and the human orders its five vacancies from best to worst.**
This is different from ranking many candidates for one vacancy. Human vacancy IDs
1 through 5 map to CSV row position; the CSV's original IDs are 8, 37, 90, 207,
and 499. Rankings cannot be inverted to infer which CVs are best for a vacancy.

The annotation file explicitly defines array position as best-to-worst vacancy
order. Two rows from annotator 1 repeat a vacancy ID and omit another, so they
are malformed permutations under this definition. The experiment excludes only
those two rater/query rows and preserves the corresponding annotator 2 rows.
It does not repair the labels, treat their duplicates as ties, or average raters
into an inferred consensus. This leaves 28 valid queries for annotator 1 and 30
for annotator 2: 58 correlated query/rater observations, not 58 independent CVs.

The publisher XML was reviewed from
[the paper's publisher-hosted XML](https://mdpi-res.com/d_attachment/information/information-14-00468/article_deploy/information-14-00468.xml)
and retained locally as `source/paper.xml`, SHA256
`ca0d7f6b7b97915ab2392d18f79f5914d4063a126267b03912ad52b2c314a67b`.
Its generic description of rank arrays is supplemented by the pinned annotation
file's explicit ordered-ID definition. These methods and metrics do not reproduce
the paper's reported experiment or attempt to resolve its data inconsistencies.

## Fixed methods and metrics

Three lexical methods are compared without training or tuning against labels:

- Word-set Jaccard similarity.
- BM25 with `k1=1.2`, `b=0.75`, positive Robertson IDF, and binary query-term
  frequency.
- TF-IDF cosine similarity with raw term counts, smooth IDF
  `1 + log((N + 1)/(df + 1))`, and L2 normalization.

All use the complete CV document text against each vacancy's title and
description. They share a fixed Unicode-normalizing tokenizer that preserves
language suffixes such as `C++` and `C#`, with no stop-word removal or stemming.
IDF and document-length statistics use only the five vacancies. These are
lexical retrieval methods, not semantic embedding models.

Each method is assessed separately against each human annotator:

- **Pairwise agreement:** fraction of job pairs put in the human's order.
  Predicted score ties receive half credit.
- **Top-1 agreement:** whether the method chooses that human's first-choice job.
  A tied top score receives `1 / tied_count` credit if it contains that job.
- **MRR of the human's first choice:** reciprocal predicted position of the
  human's favorite job, averaged uniformly over any tied positions.

No cardinal relevance scores are supplied, so the experiment does not invent
NDCG gains from ordinal positions. Its aggregate results are descriptive: the
small number of jobs, shared CVs, inconsistent rows, and rater disagreement
prevent a broad claim about hiring quality or a reliable winning algorithm.

## Recorded results

`run-1/report.json` contains the complete aggregate results and provenance:

| Method | Pairwise agreement | Top-1 agreement | MRR |
| --- | ---: | ---: | ---: |
| Uniform random expectation | 0.5000 | 0.2000 | 0.4567 |
| Lexical Jaccard | 0.4983 | 0.2759 | 0.4839 |
| BM25 | 0.6155 | 0.3793 | 0.5779 |
| TF-IDF cosine | 0.6121 | 0.3793 | 0.5859 |

The table pools the 58 valid query/rater observations. The report also retains
per-rater metrics: BM25 pairwise agreement is 0.6643 for annotator 1 and 0.5700
for annotator 2; TF-IDF is 0.6714 and 0.5567. The raters themselves agree on
0.5679 of job-pair orderings and choose the same first job for 0.1786 of their
28 shared valid CVs. Their agreement is contextual information, not an upper
bound on model performance.

BM25 and TF-IDF have higher observed agreement than lexical Jaccard here. This
supports investigating richer text features; it does not demonstrate an
improvement over Model A. Its existing five inputs require trusted structured
required/preferred skills, which this benchmark does not supply. The script
does not invent those fields or replay Model A with guessed inputs.

For the subsequent frozen MiniLM comparison on the same documents, raters and
lexical references, see [the semantic benchmark](matching-semantic-benchmark.md).

## Run and verify

From the repository root, with the research environment installed:

```bash
# First run only: download the exact pinned archive using curl with TLS checks.
.venv-research/bin/python -m scripts.matching_text_benchmark \
  --download --output .local/matching-human-benchmark/run-new

# If the source archive is already present, omit --download.
.venv-research/bin/python -m scripts.matching_text_benchmark \
  --output .local/matching-human-benchmark/run-replay

.venv-research/bin/python -m unittest \
  tests.research.test_matching_text_benchmark -v
```

Output directories must be new. Before publication, the script validates the
archive hash, exact source inventory, DOCX parsing, CSV row join, and annotation
shape, then independently replays the deterministic aggregate calculation.
Complete `protocol.json` and `report.json` files are published together by a
directory rename. Neither file includes raw text, individual candidate scores,
or individual human orderings. The code has no production integration.
