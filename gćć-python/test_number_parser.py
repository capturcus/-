import os

import pytest

import lexer
import morph_anal
import number_parser as np


# SGJP (db) pochodzi ze współdzielonej fixturki w conftest.py.


@pytest.fixture(scope="session")
def analyze(db):
    def _analyze(text):
        toks = lexer.lex(text + "\n")
        morphs = morph_anal.analyze(toks, db)
        return [m for m in morphs if m[0] is lexer.Token.WORD]
    return _analyze


# ---------- is_number_word ----------

@pytest.mark.parametrize("word", [
    "zero", "jeden", "dwa", "pięć", "dziewiętnaście",
    "dwadzieścia", "trzydzieści", "czterdzieści", "dziewięćdziesiąt",
    "sto", "dwieście", "czterysta", "dziewięćset",
    "tysiąc", "milion", "miliard",
])
def test_is_number_word_recognizes_numerals(analyze, word):
    toks = analyze(word)
    assert len(toks) == 1
    assert np.is_number_word(toks[0]), f"{word!r} powinno być liczebnikiem"


@pytest.mark.parametrize("word", [
    "tysięcy", "milionów", "miliardów", "tysiącami", "milionami",
])
def test_is_number_word_whitelist_for_genpl_magnitudes(analyze, word):
    """`tysięcy` etc. mają tylko tag subst w SGJP — whitelist je ratuje."""
    toks = analyze(word)
    assert np.is_number_word(toks[0])


@pytest.mark.parametrize("word", [
    "użytkownik", "kot", "pisze", "nazwa", "duży",
])
def test_is_number_word_rejects_non_numerals(analyze, word):
    toks = analyze(word)
    assert not np.is_number_word(toks[0])


# ---------- parse_number_words ----------

def _parse(analyze, text):
    return np.parse_number_words(analyze(text))


def test_parse_zero(analyze):
    assert _parse(analyze, "zero") == 0


def test_parse_one(analyze):
    assert _parse(analyze, "jeden") == 1


def test_parse_nineteen(analyze):
    assert _parse(analyze, "dziewiętnaście") == 19


def test_parse_twenty(analyze):
    assert _parse(analyze, "dwadzieścia") == 20


def test_parse_twenty_three(analyze):
    assert _parse(analyze, "dwadzieścia trzy") == 23


def test_parse_hundred(analyze):
    assert _parse(analyze, "sto") == 100


def test_parse_hundred_twenty_three(analyze):
    assert _parse(analyze, "sto dwadzieścia trzy") == 123


def test_parse_four_hundred_twenty_five(analyze):
    assert _parse(analyze, "czterysta dwadzieścia pięć") == 425


def test_parse_thousand_alone(analyze):
    """`tysiąc` sam = 1000 (max(current,1) z current=0)."""
    assert _parse(analyze, "tysiąc") == 1000


def test_parse_million_alone(analyze):
    assert _parse(analyze, "milion") == 1_000_000


def test_parse_two_thousand(analyze):
    assert _parse(analyze, "dwa tysiące") == 2_000


def test_parse_five_thousand(analyze):
    assert _parse(analyze, "pięć tysięcy") == 5_000


def test_parse_425435(analyze):
    """Główny przykład z briefingu."""
    src = "czterysta dwadzieścia pięć tysięcy czterysta trzydzieści pięć"
    assert _parse(analyze, src) == 425435


def test_parse_two_million_three_hundred(analyze):
    src = "dwa miliony trzysta tysięcy"
    assert _parse(analyze, src) == 2_300_000


def test_parse_billion(analyze):
    """1 miliard = 10**9 (po polsku, nie short scale)."""
    assert _parse(analyze, "miliard") == 10**9


def test_parse_empty_raises():
    with pytest.raises(np.NumberParseError):
        np.parse_number_words([])


def test_parse_non_numeral_raises(analyze):
    toks = analyze("użytkownik")
    with pytest.raises(np.NumberParseError):
        np.parse_number_words(toks)
