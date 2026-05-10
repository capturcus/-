import os

import pytest

import lexer
import morph_anal
import preprocess


SGJP_PATH = os.path.join(os.path.dirname(__file__), "..", "sgjp.tab")


@pytest.fixture(scope="session")
def loaded():
    return morph_anal.load(SGJP_PATH)


@pytest.fixture(scope="session")
def db(loaded):
    return loaded[0]


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


# ---------- POD scalanie ----------

def test_pod_solo(pp):
    toks = pp("pod")
    assert _kinds_values(toks) == [(lexer.Token.POD, "pod")]


def test_pod_in_subscript_expr(pp):
    """`lista pod indeksem` → WORD POD WORD."""
    toks = pp("lista pod indeksem")
    assert [t[0] for t in toks] == [
        lexer.Token.WORD, lexer.Token.POD, lexer.Token.WORD,
    ]


def test_pod_with_int_index(pp):
    """`lista pod jeden` — `jeden` zostaje INT_LIT, `pod` jako POD."""
    toks = pp("lista pod jeden")
    assert [t[0] for t in toks] == [
        lexer.Token.WORD, lexer.Token.POD, lexer.Token.INT_LIT,
    ]


def test_pod_multiseg_identifier_unchanged(pp):
    """`pod_warunkiem` (multi-seg WORD) NIE jest tokenem POD —
    operator powstaje tylko z single-seg `('pod',)`."""
    toks = pp("pod_warunkiem")
    assert [t[0] for t in toks] == [lexer.Token.WORD]


def test_pod_chain_left_assoc_tokens(pp):
    """`lista pod jeden pod dwa` — dwa tokeny POD, dwa INT_LIT."""
    toks = pp("lista pod jeden pod dwa")
    assert [t[0] for t in toks] == [
        lexer.Token.WORD,
        lexer.Token.POD, lexer.Token.INT_LIT,
        lexer.Token.POD, lexer.Token.INT_LIT,
    ]
