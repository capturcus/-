import re
from enum import Enum, auto

class Token(Enum):
    INDENT = auto()
    DEDENT = auto()
    NEWLINE = auto()
    WORD = auto()
    TEXT = auto()
    COLON = auto()
    ASSIGN = auto()
    LPAREN = auto()
    RPAREN = auto()
    ARROW = auto()
    # Produkowane wyłącznie przez preprocess.preprocess (nie przez lex).
    INT_LIT = auto()
    ARITH_OP = auto()
    TERM_OP = auto()
    CMP_OP = auto()
    POD = auto()


class Tok(tuple):
    """Token z atrybutem `line` (1-based numer linii w źródle).
    Subclass tuple — zachowuje pełną kompatybilność z `tok[0]`, `tok[1]`,
    unpackingiem `for kind, value in tokens` i tuple-equality
    (`tok == (Token.WORD, ("aby",))`)."""
    def __new__(cls, *items, line=None):
        t = super().__new__(cls, items)
        t.line = line
        return t


_TOKEN_RE = re.compile(r'"([^"]*)"|(->)|(:)|([()])|([^\s:"()]+)')


_UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
_CAMEL_RE = re.compile(rf'[{_UPPER}][^{_UPPER}]*|[^{_UPPER}]+')


def _segments(word):
    parts = []
    for piece in word.split("_"):
        if not piece:
            continue
        for sub in _CAMEL_RE.findall(piece):
            if sub:
                parts.append(sub.lower())
    return tuple(parts)


def _count_indent(line):
    n = 0
    i = 0
    while i < len(line):
        if line[i] == "\t":
            n += 1
            i += 1
        elif line[i:i + 4] == "    ":
            n += 1
            i += 4
        else:
            break
    return n


def lex(text):
    ret = []
    indent_level = 0
    last_line_no = 0
    for line_no, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        line_indents = _count_indent(line)
        indent_diff = line_indents - indent_level
        for _ in range(0, abs(indent_diff)):
            ret.append(Tok(Token.INDENT if indent_diff > 0 else Token.DEDENT, None, line=line_no))
        indent_level = line_indents
        before = len(ret)
        for m in _TOKEN_RE.finditer(stripped):
            text_, arrow, colon, paren, word = m.groups()
            if text_ is not None:
                ret.append(Tok(Token.TEXT, text_, line=line_no))
            elif arrow is not None:
                ret.append(Tok(Token.ARROW, None, line=line_no))
            elif colon is not None:
                ret.append(Tok(Token.COLON, None, line=line_no))
            elif paren is not None:
                ret.append(Tok(Token.LPAREN if paren == "(" else Token.RPAREN, None, line=line_no))
            else:
                if word == "to":
                    ret.append(Tok(Token.ASSIGN, None, line=line_no))
                else:
                    ret.append(Tok(Token.WORD, _segments(word), line=line_no))
        if len(ret) > before:
            ret.append(Tok(Token.NEWLINE, None, line=line_no))
        last_line_no = line_no
    for _ in range(indent_level):
        ret.append(Tok(Token.DEDENT, None, line=last_line_no))
    return ret
