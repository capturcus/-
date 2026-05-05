import re
from enum import Enum, auto

class Token(Enum):
    INDENT = auto()
    DEDENT = auto()
    NEWLINE = auto()
    WORD = auto()
    NUMBER = auto()
    TEXT = auto()
    BIN_OP = auto()
    COLON = auto()
    ASSIGN = auto()
    LPAREN = auto()
    RPAREN = auto()
    ARROW = auto()


_TOKEN_RE = re.compile(r'"([^"]*)"|(\d+)|(->)|(<=|>=|!=|[=+\-*/%<>])|(:)|([()])|([^\s=+\-*/%:"()<>!]+)')

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


def lex(text):
    ret = []
    indent_level = 0
    for line in text.split("\n"):
        line_indents = int((len(line) - len(line.lstrip()))/4)
        indent_diff = line_indents - indent_level
        for _ in range(0, abs(indent_diff)):
            ret.append((Token.INDENT, None) if indent_diff > 0 else (Token.DEDENT, None))
        indent_level = line_indents
        if line.strip().startswith("#"):
            continue
        before = len(ret)
        for m in _TOKEN_RE.finditer(line.strip()):
            text_, number, arrow, binop, colon, paren, word = m.groups()
            if text_ is not None:
                ret.append((Token.TEXT, text_))
            elif number is not None:
                ret.append((Token.NUMBER, int(number)))
            elif arrow is not None:
                ret.append((Token.ARROW, None))
            elif binop is not None:
                ret.append((Token.BIN_OP, binop))
            elif colon is not None:
                ret.append((Token.COLON, None))
            elif paren is not None:
                ret.append((Token.LPAREN if paren == "(" else Token.RPAREN, None))
            else:
                if word == "to":
                    ret.append((Token.ASSIGN, None))
                else:
                    ret.append((Token.WORD, _segments(word)))
        if len(ret) > before:
            ret.append((Token.NEWLINE, None))
    for _ in range(indent_level):
        ret.append((Token.DEDENT, None))
    return ret
