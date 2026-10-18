"""Fixed professional-text feature for consented outcome learning.

This is a deterministic extractor, not a trained model or verified qualification.
Callers must check both learning consents before capture. Only its bounded
scalar and specification identity enter frozen learning snapshots.
"""

import re
import unicodedata
from collections import Counter
from hashlib import sha256
from json import dumps
from math import fsum, log, sqrt

MAX_CHARACTERS = 20000
TOKEN_PATTERN = r"[^\W_]+(?:[+#]+)?(?:\.[^\W_]+)*"
CONTACT_PATTERNS = (
    r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|https?://\S+",
    r"(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)",
)
EXTRACTOR_SPEC = {
    "version": "professional-text-pair-tfidf-v1",
    "candidate_fields": ["headline", "summary"],
    "vacancy_fields": ["title", "description"],
    "join": "newline",
    "normalization": "Unicode NFKC then casefold",
    "contact_patterns_replaced_by_space_in_order": list(CONTACT_PATTERNS),
    "token_pattern": TOKEN_PATTERN,
    "stopwords": "none",
    "stemming": "none",
    "maximum_characters_per_joined_document": MAX_CHARACTERS,
    "oversized_or_empty_after_redaction": "unknown; no truncation",
    "index": "the two documents only; no labels or marketplace statistics",
    "term_frequency": "raw count",
    "idf": "1+log(3/(document_frequency+1))",
    "score": "cosine of nonnegative TF-IDF vectors over their union vocabulary",
    "interpretation": "self-declared text alignment only; not probability, verified skill or eligibility",
}
EXTRACTOR_ID = sha256(dumps(EXTRACTOR_SPEC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def professional_text_alignment(
    headline: str, summary: str, title: str, description: str
) -> tuple[float | None, str | None]:
    """Return unknown for absent text; zero for two present disjoint texts.

    Contact redaction is limited pattern matching. It does not establish that
    free prose is anonymous or contains no protected personal information.
    """
    if any(not isinstance(value, str) for value in (headline, summary, title, description)):
        return None, None
    texts = (headline + "\n" + summary, title + "\n" + description)
    if any(len(value) > MAX_CHARACTERS for value in texts):
        return None, None
    counters = []
    for value in texts:
        value = unicodedata.normalize("NFKC", value).casefold()
        for pattern in CONTACT_PATTERNS:
            value = re.sub(pattern, " ", value)
        counter = Counter(re.findall(TOKEN_PATTERN, value))
        if not counter:
            return None, None
        counters.append(counter)
    first, second = counters
    vocabulary = set(first) | set(second)
    weights = {word: 1 + log(3 / (int(word in first) + int(word in second) + 1)) for word in vocabulary}
    norm = sqrt(fsum((count * weights[word]) ** 2 for word, count in first.items())) * sqrt(
        fsum((count * weights[word]) ** 2 for word, count in second.items())
    )
    score = fsum(first[word] * second[word] * weights[word] ** 2 for word in set(first) & set(second)) / norm
    return min(1.0, max(0.0, score)), EXTRACTOR_ID
