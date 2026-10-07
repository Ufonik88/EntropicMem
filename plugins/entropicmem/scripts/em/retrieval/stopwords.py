"""The v3 retrieval stopword list (§3.6, EM-301).

§3.6 asks for "built-in English list ~180 words + config `extra_stopwords`".
**This is the same 180-word set the v2 engine already uses** (the module-level
``scripts/stopwords.py`` written for EM-104), copied rather than re-derived: the
two engines then agree about which words carry no discriminative power, and a
chunk could not silently change ranking in one and not the other.

``extra_stopwords`` has no config source yet — there is no ``em/config.py`` — so
:func:`em.retrieval.query.analyze` takes it as a parameter and EM-407 wires it.

Stdlib-only data module; no imports, no side effects.
"""

from typing import FrozenSet

__all__ = ["STOPWORDS"]

STOPWORDS: FrozenSet[str] = frozenset({
    "a", "about", "above", "after", "again", "against", "ain", "all", "also", "am", "among",
    "an", "and", "another", "any", "are", "aren", "around", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can", "could", "couldn", "d",
    "did", "didn", "do", "does", "doesn", "doing", "don", "down", "during", "each", "either",
    "else", "every", "everyone", "everything", "everywhere", "few", "for", "from", "further",
    "had", "hadn", "has", "hasn", "have", "haven", "having", "he", "her", "here", "hers",
    "herself", "him", "himself", "his", "how", "however", "i", "if", "in", "into", "is", "isn",
    "it", "its", "itself", "just", "ll", "m", "ma", "many", "may", "me", "might", "mightn",
    "more", "most", "much", "must", "mustn", "my", "myself", "needn", "neither", "no", "none",
    "nor", "not", "now", "o", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "re", "s", "same", "shall", "shan", "she",
    "should", "shouldn", "so", "some", "such", "t", "than", "that", "the", "their", "theirs",
    "them", "themselves", "then", "there", "therefore", "these", "they", "this", "those",
    "through", "throughout", "to", "too", "under", "until", "up", "ve", "very", "was", "wasn",
    "we", "were", "weren", "what", "when", "where", "which", "while", "who", "whom", "whose",
    "why", "will", "with", "within", "without", "won", "would", "wouldn", "y", "you", "your",
    "yours", "yourself", "yourselves",
})
