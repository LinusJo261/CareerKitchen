# Frozen MiniLM human-ranking experiment

This offline comparison adds semantic document similarity to the existing
[human-ranking text benchmark](matching-human-benchmark.md). It uses a pretrained
encoder with fixed weights. It does not retrain the structured five-feature
Model A, change live matching, or supply missing essential-requirement fields.

## Model and fixed protocol

The encoder is
[`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/blob/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/README.md),
pinned to revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Its model card
declares Apache-2.0 and describes 384-dimensional sentence/paragraph embeddings.
The default model truncates longer text, so this experiment explicitly covers
complete documents using overlapping windows.

The pinned safetensors file has SHA256
`53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`,
as published on its [official file page](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/blob/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/model.safetensors).

The following choices were fixed before computing semantic benchmark scores:

1. Use the same five vacancy titles and descriptions and the complete text of
   the first 30 CVs as the lexical benchmark.
2. Tokenize with the pinned model tokenizer, without special tokens or
   truncation. Divide the token IDs into windows of at most 200 subwords with
   40-token overlap. Retain every token, including the final window.
3. Add the model's special tokens to each window directly from its token IDs.
   Do not decode text and re-tokenize it. This avoids an extra source of token
   changes and prevents silent truncation. The pinned BERT template is
   `[CLS]=101`, unchanged chunk IDs, `[SEP]=102`, then right padding with ID 0.
   Attention masks exclude padding; token type IDs are zero. The adapter checks
   this construction against the installed tokenizer on a fixed fictional probe.
4. Run the model's built-in Transformer, mean pooling, and normalization on CPU
   in evaluation/inference mode. Use float32, batches of 32, one torch thread,
   deterministic algorithms, and seed 0. Normalize each chunk vector.
5. Average all chunk vectors equally within each document, then normalize the
   mean. Compare CVs with each vacancy using cosine similarity. Aggregation uses
   float64. Apply exactly the same document scheme to vacancies and CVs.

There is one semantic configuration, with no fine-tuning, label-based parameter
selection, seed search, section extraction, or weighted lexical blending.
Equal chunk averaging is a simple fixed policy; it may dilute a short relevant
experience section and overrepresent context in overlapping windows.

BM25, TF-IDF, and word-set Jaccard scores are recomputed using the existing
`matching_text_benchmark` functions without changing their inputs or parameters.
Their results therefore remain directly comparable on this benchmark.

## Labels, metrics, and interpretation

The exact source archive, hash checks, CSV row mapping, and annotation parsing
come from the existing benchmark. Two malformed annotator-1 rows remain excluded
without repairs. Annotator 1 contributes 28 query/rater rows and annotator 2
contributes 30. Both raters are reported separately and pooled descriptively.

Metrics remain pairwise agreement, top-1 agreement, MRR of the human's first
choice, and predicted pair-tie rate. Existing uniform tie handling is preserved.
The report also retains human inter-rater agreement and the uniform-random
reference. No cardinal relevance scores or NDCG gains are invented.

The 58 pooled observations share 30 CVs and five vacancies. They are correlated;
they cannot establish a reliable winning method or broad hiring accuracy. The
task ranks five jobs for a given CV, rather than ranking candidates for a given
job. Its labels cannot simply be inverted to evaluate candidate retrieval.
Earlier lexical benchmark results have already been inspected, making this an
exploratory comparison rather than a new untouched test set.

The encoder is general-purpose English text similarity, with unknown overlap
between its original training texts and this public benchmark. Its scores are
not calibrated probabilities and do not measure candidate interest, employer
interest, satisfaction, or hiring outcomes. Frozen pretrained weights can also
carry biases from their original data.

## Recorded results

The completed run is
`.local/matching-human-benchmark/minilm-1/report.json`. Higher values are better
for all three ranking metrics below. The table pools the same 58 valid
query/rater rows, without treating them as independent CVs.

| Method | Pairwise agreement | Top-1 agreement | MRR |
| --- | ---: | ---: | ---: |
| Uniform random expectation | 0.5000 | 0.2000 | 0.4567 |
| Lexical Jaccard | 0.4983 | 0.2759 | 0.4839 |
| BM25 | 0.6155 | 0.3793 | 0.5779 |
| TF-IDF cosine | 0.6121 | 0.3793 | 0.5859 |
| Frozen chunked MiniLM | 0.5500 | 0.1897 | 0.4302 |

The pretrained encoder did **not** improve this benchmark over BM25 or TF-IDF.
Its observed first-choice agreement is 18.97%, compared with 37.93% for both
lexical methods and a 20% uniform-random expectation. This small experiment does
not establish statistically reliable superiority or inferiority on other data.
The fixed configuration was not retuned after inspecting these scores, and no
semantic feature was promoted into Model A or application matching.

The raters respond differently to the semantic rankings. MiniLM top-1 agreement
is 7.14% for annotator 1 and 30.00% for annotator 2; BM25 is 46.43% and 30.00%.
MiniLM pairwise agreement is 0.4821 and 0.6133 respectively. The saved report keeps
these separate instead of inventing consensus labels. All lexical results and
human inter-rater agreement match the earlier lexical experiment unchanged.

All 35 documents required multiple windows: 144 chunks total, document lengths
234–1,138 subword tokens, and at most seven chunks per document. Zero documents
were truncated. The run used Python 3.12.15, sentence-transformers 5.7.0, torch
2.14.1, transformers 5.20.1, NumPy 2.5.4, tokenizers 0.23.3, safetensors 0.8.0,
and huggingface-hub 2.2.0. The protocol SHA256 is
`b3ea94f3b0c6411246e43af054dafff9a7b5f7fa6e330f0ed1eec088aab50689`;
JSON embedding-cache replay passed before publication.

## Local files and replay

The model is loaded from an ignored local snapshot using
`local_files_only=True`, `trust_remote_code=False`, and
`model_kwargs={"use_safetensors": True}`. The script accepts only known built-in
Transformer/Pooling/Normalize module paths and the canonical inference/config
files. It rejects Python files, pickle/bin weights, unexpected files, symlinks,
dynamic `auto_map` code, and a changed pinned safetensors SHA256.

The pinned model README, including its license declaration, stays with the
ignored local weights. The source archive retains its own GPL-3.0 license,
instructions, and paper citation. No raw CVs, vacancy text, weights, or individual
human orderings are committed or redistributed.

Every complete run publishes a new output directory containing:

- `protocol.json`: fixed preprocessing, model revision, all local model/source
  file hashes, both implementation script hashes, software versions, and the unchanged lexical parameters. It is
  serialized before inference or ranking.
- `embeddings.json`: JSON numeric vectors and content hashes in fixed document
  order; no document text, individual scores, or human rankings. This cache is
  ignored local research data, not an application model artifact.
- `report.json`: aggregate per-rater and pooled metrics, aggregate chunk counts,
  hashes of protocol/cache, software provenance, and limitations.

Before atomic directory publication, the script replays the aggregate results
from the serialized JSON embeddings and checks equality. This verifies cache
serialization and deterministic scoring; it does not claim identical floating
point inference across different hardware or library versions. Failed runs do
not publish partial output, and existing outputs are never overwritten.

## Run and verify

Use a separate supported Python environment for torch, rather than changing API
dependencies. Python 3.12 is suitable; the existing Python 3.15 research
environment may have no compatible torch wheel. This checkout's optional
environment is `.local/semantic-venv`, provisioned using the ignored local
`.local/semantic-tools/bin/uv` executable and managed Python under
`.local/semantic-python`. Its packages can be installed with
`uv pip install --python .local/semantic-venv/bin/python -r requirements-research-semantic.txt`;
the environment does not need its own pip installation.

From the repository root, with a supported Python environment:

```bash
# In an environment with a supported Python, install optional experiment packages.
python -m pip install -r requirements-research-semantic.txt

# The source archive is the existing pinned benchmark download. Acquire the
# canonical model inference files at the exact revision above before this step.
python -m scripts.matching_semantic_benchmark \
  --model-dir .local/matching-human-benchmark/models/all-MiniLM-L6-v2 \
  --output .local/matching-human-benchmark/minilm-1

# Fictional unit tests use a mock encoder and need no torch or model download.
.venv-research/bin/python -m unittest \
  tests.research.test_matching_semantic_benchmark -v
```

In this checkout, use `.local/semantic-venv/bin/python` in place of `python` for
the benchmark command. Choose a new output directory when replaying a completed
run. The unit tests still run in `.venv-research` without the optional packages.

`--model-dir` must contain `README.md`, `model.safetensors`, `config.json`,
`config_sentence_transformers.json`, `modules.json`, `sentence_bert_config.json`,
`tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`, `vocab.txt`,
and `1_Pooling/config.json`. Optional files are `LICENSE`, `.gitattributes`, and
`2_Normalize/config.json`; other files are rejected. The source defaults to
`.local/matching-human-benchmark/source/repository.zip`.

All model/source downloads happen before inference. The benchmark script itself
does not fetch remote code or weights. Follow the exact revision and recorded
hashes when reproducing the experiment; using an unpinned current model would be
a different experiment.
