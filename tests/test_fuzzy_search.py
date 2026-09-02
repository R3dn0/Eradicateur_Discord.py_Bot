import pytest
from bot.utils.fuzzy_search import (
    normalize_fuzzy_str,
    damerau_levenshtein_distance,
    fuzzy_match_member,
    get_max_allowed_errors,
)


def test_normalize_fuzzy_str():
    assert normalize_fuzzy_str("R3dn0") == "redno"
    assert normalize_fuzzy_str("Éradicateur") == "eradicateur"
    assert normalize_fuzzy_str("L0RD_777") == "lord_ttt"
    assert normalize_fuzzy_str("T3st@123") == "testai2e"


def test_damerau_levenshtein_distance():
    assert damerau_levenshtein_distance("redno", "redno") == 0
    assert damerau_levenshtein_distance("redno", "radno") == 1
    assert damerau_levenshtein_distance("rdeno", "redno") == 1  # Transposition
    assert damerau_levenshtein_distance("redno", "reno") == 1   # Deletion
    assert damerau_levenshtein_distance("redno", "rednoo") == 1 # Insertion


def test_get_max_allowed_errors():
    assert get_max_allowed_errors(1) == 0
    assert get_max_allowed_errors(3) == 0
    assert get_max_allowed_errors(4) == 1
    assert get_max_allowed_errors(6) == 1
    assert get_max_allowed_errors(7) == 2
    assert get_max_allowed_errors(10) == 3


def test_fuzzy_match_member():
    # Leetspeak and case
    assert fuzzy_match_member("redno", "R3dn0 (@r3dn0)", 135489084385787905) is True
    assert fuzzy_match_member("r3dn0", "Redno", 135489084385787905) is True
    assert fuzzy_match_member("radno", "R3dn0", 135489084385787905) is True
    assert fuzzy_match_member("rdeno", "R3dn0", 135489084385787905) is True

    # Short strict strings (no false positive)
    assert fuzzy_match_member("tom", "Tim", 111) is False
    assert fuzzy_match_member("tom", "Tommy (@tommy)", 111) is True

    # Long names with typos
    assert fuzzy_match_member("eradictor", "Eradicateur", 222) is True
    assert fuzzy_match_member("eradicateur", "Eradicateur", 222) is True

    # Discord ID match
    assert fuzzy_match_member("135489", "RandomName", 135489084385787905) is True
