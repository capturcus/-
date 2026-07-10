import os

import pytest

import lexer
import morph_anal
import preprocess


# SGJP (db) pochodzi ze współdzielonej fixturki w conftest.py.


@pytest.fixture(scope="session")
def pp(db):
    def _pp(text):
        toks = lexer.lex(text + "\n")
        morphs = morph_anal.analyze(toks, db)
        return [
            t for t in preprocess.preprocess(morphs)
            if t[0] not in (lexer.Token.NEWLINE,)
        ]
    return _pp


def _kinds_values(toks):
    return [(t[0], t[1]) for t in toks]


# ---------- CMP_OP scalanie ----------

@pytest.mark.parametrize("src,op", [
    ("mniejsze od", "<"),
    ("większe od", ">"),
    ("mniejsze równe", "<="),
    ("większe równe", ">="),
    ("równe", "="),
    ("nierówne", "!="),
])
def test_cmp_op_scaling(pp, src, op):
    toks = pp(src)
    assert _kinds_values(toks) == [(lexer.Token.CMP_OP, op)]


@pytest.mark.parametrize("src,op", [
    # odmiany rodzajowo-przypadkowe komparatywów
    ("mniejszy od", "<"),
    ("mniejsza od", "<"),
    ("mniejszym od", "<"),
    ("większy od", ">"),
    ("większa od", ">"),
    ("większym od", ">"),
    # dwuwyrazowe z odmienioną formą `równy`
    ("mniejszy równy", "<="),
    ("mniejsza równa", "<="),
    ("większy równy", ">="),
    ("większa równa", ">="),
    # odmiany `równy` / `nierówny` solo
    ("równy", "="),
    ("równa", "="),
    ("nierówny", "!="),
    ("nierówna", "!="),
    ("nierównym", "!="),
])
def test_cmp_op_inflected_forms(pp, src, op):
    """Operatory porównania działają we wszystkich formach gramatycznych."""
    toks = pp(src)
    assert _kinds_values(toks) == [(lexer.Token.CMP_OP, op)]


def test_positive_degree_is_not_cmp_op(pp):
    """`mały`/`duży` w stopniu równym to zwykłe słowa, nie operatory."""
    toks = pp("mały od")
    assert toks[0][0] is lexer.Token.WORD


def test_cmp_with_args(pp):
    # pięć mniejsze od dziesięć
    toks = pp("pięć mniejsze od dziesięć")
    assert _kinds_values(toks) == [
        (lexer.Token.INT_LIT, 5),
        (lexer.Token.CMP_OP, "<"),
        (lexer.Token.INT_LIT, 10),
    ]


# ---------- ARITH_OP / TERM_OP ----------

@pytest.mark.parametrize("src,kind,op", [
    ("plus", lexer.Token.ARITH_OP, "+"),
    ("minus", lexer.Token.ARITH_OP, "-"),
    ("razy", lexer.Token.TERM_OP, "*"),
])
def test_arith_term_op(pp, src, kind, op):
    toks = pp(src)
    assert _kinds_values(toks) == [(kind, op)]


def test_arith_between_numbers(pp):
    toks = pp("dwa plus trzy")
    assert _kinds_values(toks) == [
        (lexer.Token.INT_LIT, 2),
        (lexer.Token.ARITH_OP, "+"),
        (lexer.Token.INT_LIT, 3),
    ]


def test_term_between_numbers(pp):
    toks = pp("dwa razy trzy")
    assert _kinds_values(toks) == [
        (lexer.Token.INT_LIT, 2),
        (lexer.Token.TERM_OP, "*"),
        (lexer.Token.INT_LIT, 3),
    ]


# ---------- INT_LIT scalanie sekwencji liczebnikowych ----------

def test_single_number(pp):
    toks = pp("pięć")
    assert _kinds_values(toks) == [(lexer.Token.INT_LIT, 5)]


def test_multi_number(pp):
    toks = pp("sto dwadzieścia trzy")
    assert _kinds_values(toks) == [(lexer.Token.INT_LIT, 123)]


def test_large_number(pp):
    toks = pp("czterysta dwadzieścia pięć tysięcy czterysta trzydzieści pięć")
    assert _kinds_values(toks) == [(lexer.Token.INT_LIT, 425435)]


def test_two_numbers_separated_by_op(pp):
    toks = pp("sto plus dwieście")
    assert _kinds_values(toks) == [
        (lexer.Token.INT_LIT, 100),
        (lexer.Token.ARITH_OP, "+"),
        (lexer.Token.INT_LIT, 200),
    ]


# ---------- Mieszane / kolejność ----------

def test_cmp_before_numbers_preserves_pieces(pp):
    """`mniejsze od pięć` — `pięć` nie może być wciągnięte do scalania cmp."""
    toks = pp("mniejsze od pięć")
    assert _kinds_values(toks) == [
        (lexer.Token.CMP_OP, "<"),
        (lexer.Token.INT_LIT, 5),
    ]


def test_word_passthrough(pp):
    """Słowa nie-operatorowe i nie-liczbowe przechodzą bez zmian."""
    toks = pp("użytkownik")
    assert toks[0][0] is lexer.Token.WORD


# ---------- `pod` bez specjalnego traktowania ----------

def test_pod_is_ordinary_word(pp):
    """`pod` to zwykłe słowo (przyimek) — preprocesor go nie rusza."""
    toks = pp("pod warunkiem")
    assert [t[0] for t in toks] == [lexer.Token.WORD, lexer.Token.WORD]
    assert toks[0][1] == ("pod",)




# ---------- literały logiczne (BOOL_LIT) ----------

def test_bool_literal_prawda(pp):
    toks = pp("prawda")
    assert toks[0][0] is lexer.Token.BOOL_LIT
    assert toks[0][1] is True


def test_bool_literal_fałsz(pp):
    toks = pp("fałsz")
    assert toks[0][0] is lexer.Token.BOOL_LIT
    assert toks[0][1] is False


def test_bool_literal_inflected_forms(pp):
    # rozpoznawanie po lemmie — formy odmienione też są literałami
    toks = pp("prawdę fałszem")
    assert [t[0] for t in toks] == [lexer.Token.BOOL_LIT, lexer.Token.BOOL_LIT]
    assert [t[1] for t in toks] == [True, False]


def test_bool_literal_capitalized_is_not_literal(pp):
    # `Prawda` ma lemmę ("Prawda",) — to przestrzeń typów, nie literał
    toks = pp("Prawda")
    assert toks[0][0] is lexer.Token.WORD


def test_bool_literal_multiseg_is_not_literal(pp):
    toks = pp("prawda_objawiona")
    assert toks[0][0] is lexer.Token.WORD
