"""Preprocesor tokenów po analizie morfologicznej.

Cztery przebiegi:
1. Scal pary `mniejsze+od / większe+od / mniejsze+równe / większe+równe`
   oraz solo `równe / nierówne` w token `CMP_OP`.
2. Oznacz solo `plus / minus` jako `ARITH_OP`, `razy` jako `TERM_OP`.
3. Oznacz solo `pod` (single-seg WORD) jako `POD` — operator subscript.
4. Scal maksymalne sekwencje liczebnikowe (`is_number_word`) w token `INT_LIT`.

Kolejność jest istotna: porównania PRZED liczebnikami, żeby `mniejsze od pięć`
nie zgubiło `pięć` w czasie scalania ciągu liczebnikowego.

Rozpoznawanie operatorów porównania: PO SURFACE FORMIE — bo w SGJP
`mniejsze` ma lemmę `mały` (comparative), więc po lemacie nie da się odróżnić
od zwykłego `mały`. Konwencja matematyczna używa neutrum singularis:
`mniejsze/większe/równe/nierówne`.

Operatory arytmetyczne (plus/minus/razy) i `równe/nierówne` rozpoznawane
po canonical lemma (bo lemmy są już kanoniczne). `pod` jako operator —
po canonical, tylko gdy jest pojedynczym segmentem (multi-seg identyfikatory
typu `pod_warunkiem` zostają WORD-em).
"""

import lexer
from morph_anal import canonical
from number_parser import is_number_word, parse_number_words


_CMP_2WORD = {
    ("mniejsze", "od"): "<",
    ("większe", "od"): ">",
    ("mniejsze", "równe"): "<=",
    ("większe", "równe"): ">=",
}

_CMP_1WORD_LEMMAS = {
    ("równy",): "=",
    ("nierówny",): "!=",
}

_ARITH_SURFACE = {"plus": "+", "minus": "-"}
_TERM_SURFACE = {"razy": "*"}


def _canon_or_none(tok):
    if tok is None or tok[0] is not lexer.Token.WORD:
        return None
    return canonical(tok)


def _surface_or_none(tok):
    """Surface form pojedynczego segmentu, lub None."""
    if tok is None or tok[0] is not lexer.Token.WORD:
        return None
    if len(tok[1]) != 1:
        return None
    return tok[1][0]


def _scan_cmp(tokens):
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        s1 = _surface_or_none(tokens[i])
        s2 = _surface_or_none(tokens[i + 1]) if i + 1 < n else None
        if s1 is not None and s2 is not None and (s1, s2) in _CMP_2WORD:
            out.append((lexer.Token.CMP_OP, _CMP_2WORD[(s1, s2)], None))
            i += 2
            continue
        c1 = _canon_or_none(tokens[i])
        if c1 in _CMP_1WORD_LEMMAS:
            out.append((lexer.Token.CMP_OP, _CMP_1WORD_LEMMAS[c1], None))
            i += 1
            continue
        out.append(tokens[i])
        i += 1
    return out


def _scan_arith(tokens):
    out = []
    for t in tokens:
        s = _surface_or_none(t)
        if s in _ARITH_SURFACE:
            out.append((lexer.Token.ARITH_OP, _ARITH_SURFACE[s], None))
        elif s in _TERM_SURFACE:
            out.append((lexer.Token.TERM_OP, _TERM_SURFACE[s], None))
        else:
            out.append(t)
    return out


def _scan_pod(tokens):
    out = []
    for t in tokens:
        if _canon_or_none(t) == ("pod",):
            out.append((lexer.Token.POD, "pod", None))
        else:
            out.append(t)
    return out


def _scan_numbers(tokens):
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t[0] is lexer.Token.WORD and is_number_word(t):
            j = i + 1
            while (
                j < n
                and tokens[j][0] is lexer.Token.WORD
                and is_number_word(tokens[j])
            ):
                j += 1
            value = parse_number_words(tokens[i:j])
            out.append((lexer.Token.INT_LIT, value, None))
            i = j
            continue
        out.append(t)
        i += 1
    return out


def preprocess(tokens):
    return _scan_numbers(_scan_pod(_scan_arith(_scan_cmp(tokens))))
