"""
stopwords.py — English stopword list for the FTS5 query builder.

These words carry no discriminative power in a free-text MATCH query: every
one of them appears in almost every document, so as FTS terms they drown the
real words and make junk queries match trivially (finding R2). The shared
builder in memory_engine.build_fts_query() drops them before building terms.

Stdlib-only data module — no imports, no side effects.
"""

from typing import FrozenSet

STOPWORDS: FrozenSet[str] = frozenset({
    # pronouns
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your",
    "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she",
    "her", "hers", "herself", "it", "its", "itself", "they", "them", "their",
    "theirs", "themselves",
    # determiners / demonstratives
    "a", "an", "the", "this", "that", "these", "those", "some", "any", "all",
    "each", "every", "everyone", "everything", "everywhere", "either",
    "neither", "no", "nor", "none", "another", "both", "few", "many", "much",
    "more", "most", "other", "such",
    # interrogatives / relativizers
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",

    # verbs: be / have / do + modals + common auxiliaries
    "am", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "having", "do", "does", "did", "doing", "can", "will", "would",
    "shall", "should", "could", "might", "must", "ought", "may", "just",
    # prepositions / particles
    "of", "at", "by", "for", "with", "about", "against", "between", "into",
    "through", "throughout", "during", "before", "after", "above", "below",
    "to", "from", "up", "down", "in", "out", "on", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "where", "when",
    "while", "until", "within", "without", "around", "among",
    # conjunctions / adverbs (function words only)
    "and", "but", "if", "or", "because", "as", "so", "than", "too", "very",
    "also", "else", "however", "therefore",
    "now", "only", "own", "same", "not",
    # contraction fragments (tokenizer splits "don't" -> "don" + "t")
    "s", "t", "d", "m", "o", "y", "ll", "re", "ve", "ain", "aren", "couldn",
    "didn", "doesn", "don", "hadn", "hasn", "haven", "isn", "ma", "mightn",
    "mustn", "needn", "shan", "shouldn", "wasn", "weren", "won", "wouldn",
})
