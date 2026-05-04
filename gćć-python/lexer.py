from enum import Enum, auto

class Token(Enum):
    INDENT = auto()
    DEDENT = auto()
    WORD = auto()
    NUMBER = auto()
    TEXT = auto()
    BIN_OP = auto()
    COLON = auto()
    

def lex(text):
    ret = []
    indent_level = 0
    for line in text.split("\n"):
        line_indents = int((len(line) - len(line.lstrip()))/4)
        indent_diff = line_indents - indent_level
        for _ in range(0, abs(indent_diff)):
            ret.append(Token.INDENT if indent_diff > 0 else Token.DEDENT)
        indent_level = line_indents
        if line.strip().startswith("#"):
            continue
        for word in line.strip().split():
            print(word)
    return ret
