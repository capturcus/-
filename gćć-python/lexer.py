import re
from enum import Enum, auto

class Token(Enum):
    INDENT = auto()
    DEDENT = auto()
    NEWLINE = auto()
    WORD = auto()
    TEXT = auto()
    CHAR = auto()
    COLON = auto()
    ASSIGN = auto()
    LPAREN = auto()
    RPAREN = auto()
    ARROW = auto()
    QUESTION = auto()
    # Produkowane wyłącznie przez preprocess.preprocess (nie przez lex).
    INT_LIT = auto()
    BOOL_LIT = auto()
    ARITH_OP = auto()
    TERM_OP = auto()
    CMP_OP = auto()


class Tok(tuple):
    """Token z atrybutem `line` (1-based numer linii w źródle).
    Subclass tuple — zachowuje pełną kompatybilność z `tok[0]`, `tok[1]`,
    unpackingiem `for kind, value in tokens` i tuple-equality
    (`tok == (Token.WORD, ("aby",))`)."""
    def __new__(cls, *items, line=None):
        t = super().__new__(cls, items)
        t.line = line
        return t


_TOKEN_RE = re.compile(
    r'"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'|(->)|(:)|([()])|(\?)'
    r'|([^\s:"\'()?]+)')


_ESC_MAP = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "0": "\0",
}


def _unescape_string(raw, line_no):
    """Przetwarza escape sequences w surowej zawartości literału stringowego.
    Wspierane: \\n \\t \\r \\\\ \\" \\0. Nieznany escape → InterpreterError."""
    from ast_nodes import InterpreterError
    out = []
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            # Regex `\\.` powinien temu zapobiec, ale defensywnie.
            raise InterpreterError(
                "wiszący backslash w literale stringowym", line=line_no,
            )
        esc = raw[i + 1]
        if esc not in _ESC_MAP:
            raise InterpreterError(
                f"nieznany escape '\\{esc}' w literale stringowym; "
                f"wspierane: \\n \\t \\r \\\\ \\\" \\' \\0",
                line=line_no,
            )
        out.append(_ESC_MAP[esc])
        i += 2
    return "".join(out)


_UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
_CAMEL_RE = re.compile(rf'[{_UPPER}][^{_UPPER}]*|[^{_UPPER}]+')


def _segments(word):
    parts = []
    for piece in word.split("_"):
        if not piece:
            continue
        for sub in _CAMEL_RE.findall(piece):
            if sub:
                parts.append(sub)  # zachowaj oryginalny case dla canonical/cap
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
            text_, char_, arrow, colon, paren, question, word = m.groups()
            if text_ is not None:
                ret.append(Tok(Token.TEXT, _unescape_string(text_, line_no), line=line_no))
            elif char_ is not None:
                znak = _unescape_string(char_, line_no)
                if len(znak) != 1:
                    from ast_nodes import InterpreterError
                    raise InterpreterError(
                        f"literał znakowy '{char_}' musi zawierać dokładnie "
                        f"jeden znak",
                        line=line_no,
                    )
                ret.append(Tok(Token.CHAR, znak, line=line_no))
            elif arrow is not None:
                ret.append(Tok(Token.ARROW, None, line=line_no))
            elif colon is not None:
                ret.append(Tok(Token.COLON, None, line=line_no))
            elif question is not None:
                ret.append(Tok(Token.QUESTION, None, line=line_no))
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
