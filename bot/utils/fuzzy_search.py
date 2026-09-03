import unicodedata
from difflib import SequenceMatcher

_LEET_MAP = str.maketrans({
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "@": "a",
    "$": "s",
})


def normalize_fuzzy_str(text: str) -> str:
    """
    Normalizes text for fuzzy member matching:
    - Lowercase
    - Unicode accent removal (NFKD)
    - Leetspeak substitution (3->e, 0->o, 4->a, etc.)
    """
    if not text:
        return ""
    lowered = text.lower()
    nfkd = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.translate(_LEET_MAP)


def damerau_levenshtein_distance(s1: str, s2: str) -> int:
    """
    Computes the Damerau-Levenshtein distance between two strings
    (supporting insertions, deletions, substitutions, and adjacent transpositions).
    """
    len1, len2 = len(s1), len(s2)
    if len1 == 0:
        return len2
    if len2 == 0:
        return len1

    d = [[0] * (len2 + 1) for _ in range(len1 + 1)]

    for i in range(len1 + 1):
        d[i][0] = i
    for j in range(len2 + 1):
        d[0][j] = j

    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,        # deletion
                d[i][j - 1] + 1,        # insertion
                d[i - 1][j - 1] + cost,  # substitution
            )
            # Transposition of adjacent characters
            if i > 1 and j > 1 and s1[i - 1] == s2[j - 2] and s1[i - 2] == s2[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)

    return d[len1][len2]


def get_max_allowed_errors(query_len: int) -> int:
    """
    Returns the maximum allowable edit distance based on query length:
    - <= 3 chars: 0 errors (strict / substring only)
    - 4 to 6 chars: 1 error
    - 7 to 9 chars: 2 errors
    - >= 10 chars: 3 errors
    """
    if query_len <= 3:
        return 0
    if query_len <= 6:
        return 1
    if query_len <= 9:
        return 2
    return 3


def fuzzy_match_member(query: str, target_name: str, target_id: str | int | None = None) -> bool:
    """
    Determines if target member matches query with normalization and typo tolerance.
    Supports matching against target name, display name, username, and Discord ID.
    """
    q = query.strip()
    if not q:
        return True

    # Check Discord ID direct substring match
    if target_id is not None and q in str(target_id):
        return True

    norm_q = normalize_fuzzy_str(q)
    norm_target = normalize_fuzzy_str(target_name)

    if not norm_q:
        return True

    # 1. Exact or Substring match (0 errors needed)
    if norm_q in norm_target:
        return True

    q_len = len(norm_q)
    max_errors = get_max_allowed_errors(q_len)
    if max_errors == 0:
        return False

    # 2. Check similarity ratio directly
    if q_len >= 4:
        ratio = SequenceMatcher(None, norm_q, norm_target).ratio()
        if ratio >= 0.72:
            return True

    # 3. Check each token/word in target
    tokens = [t for t in norm_target.replace("(", " ").replace(")", " ").replace("@", " ").split() if t]
    for token in tokens:
        if damerau_levenshtein_distance(norm_q, token) <= max_errors:
            return True
        if q_len >= 4 and SequenceMatcher(None, norm_q, token).ratio() >= 0.72:
            return True
        if len(token) >= q_len:
            prefix = token[:q_len]
            if damerau_levenshtein_distance(norm_q, prefix) <= max_errors:
                return True

    # 4. Sliding window match over norm_target
    for w_len in range(max(1, q_len - max_errors), min(len(norm_target) + 1, q_len + max_errors + 1)):
        for i in range(len(norm_target) - w_len + 1):
            window = norm_target[i:i + w_len]
            if damerau_levenshtein_distance(norm_q, window) <= max_errors:
                return True
            if q_len >= 4 and SequenceMatcher(None, norm_q, window).ratio() >= 0.75:
                return True

    return False
