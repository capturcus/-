from dataclasses import dataclass

import lexer
from morph_anal import canonical


@dataclass
class Module:
    body: list


@dataclass
class FunctionDef:
    name: tuple
    params: list
    body: list
    return_type: tuple = None


@dataclass
class Param:
    prep: tuple
    name: tuple
    case: str
    surface: tuple
    type: tuple = None


@dataclass
class StructDef:
    name: tuple
    fields: list


@dataclass
class Field:
    name: tuple
    type: tuple


@dataclass
class Phrase:
    words: list


@dataclass
class Word:
    prep: tuple
    value: object
    case: str


@dataclass
class Assignment:
    target: tuple
    value: object


@dataclass
class IntLit:
    value: int


@dataclass
class StrLit:
    value: str


@dataclass
class BinOp:
    op: str
    left: object
    right: object


@dataclass
class UnaryOp:
    op: str
    operand: object


@dataclass
class If:
    cond: object
    then_body: list
    else_body: list


@dataclass
class While:
    cond: object
    body: list


@dataclass
class Break:
    pass


@dataclass
class Return:
    value: object


@dataclass
class Not:
    operand: object


@dataclass
class And:
    left: object
    right: object


@dataclass
class Or:
    left: object
    right: object


LOGICAL_OPS = {("nie",), ("i",), ("lub",)}


class Parser:
    def __init__(self, tokens, preps=None):
        self.tokens = tokens
        self.pos = 0
        self.preps = preps or {}

    def peek(self, offset=0):
        i = self.pos + offset
        return self.tokens[i] if i < len(self.tokens) else None

    def advance(self):
        t = self.peek()
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.advance()
        if t is None or t[0] is not kind:
            print(self.peek(-2), self.peek(-1), self.peek(-0))
            raise SyntaxError(f"Expected {kind}, got {t}")
        return t

    def _skip_newlines(self):
        while self.peek() and self.peek()[0] is lexer.Token.NEWLINE:
            self.advance()

    def _is_prep(self, token):
        if token is None or token[0] is not lexer.Token.WORD:
            return False
        canon = canonical(token)
        return len(canon) == 1 and canon[0] in self.preps

    def _is_logical_op(self, token):
        return (
            token is not None
            and token[0] is lexer.Token.WORD
            and canonical(token) in LOGICAL_OPS
        )

    def _case_of(self, token):
        _, value, analyses = token
        last_case = None
        for seg, anas in zip(value, analyses):
            if not anas or len(seg) == 1:
                last_case = None
                continue
            with_case = [a for a in anas if a[1] is not None]
            if not with_case:
                last_case = None
                continue
            chosen = next((a for a in with_case if a[2] == seg), with_case[0])
            last_case = chosen[1]
        return last_case

    def parse_module(self):
        body = []
        self._skip_newlines()
        while self.peek() is not None:
            body.append(self.parse_stmt())
            self._skip_newlines()
        return Module(body)

    def parse_stmt(self):
        t = self.peek()
        if t[0] is lexer.Token.WORD:
            canon = canonical(t)
            if canon == ("aby",):
                return self.parse_func_def()
            if canon == ("definicja",):
                return self.parse_struct_def()
            if canon == ("jeśli",):
                return self.parse_if()
            if canon == ("dopóki",):
                return self.parse_while()
            if canon == ("stop",):
                self.advance()
                return Break()
            if canon == ("zwrócić",):
                self.advance()
                return Return(value=self.parse_expr())
        expr = self.parse_expr()
        if self.peek() and self.peek()[0] is lexer.Token.ASSIGN:
            self.advance()
            return Assignment(target=expr, value=self.parse_expr())
        return expr

    def parse_if(self):
        self.expect(lexer.Token.WORD)  # jeśli
        cond = self.parse_expr()
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        then_body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            then_body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        else_body = []
        t = self.peek()
        if t and t[0] is lexer.Token.WORD and canonical(t) == ("inaczej",):
            self.advance()
            t2 = self.peek()
            if t2 and t2[0] is lexer.Token.WORD and canonical(t2) == ("jeśli",):
                else_body = [self.parse_if()]
            else:
                self.expect(lexer.Token.COLON)
                self._skip_newlines()
                self.expect(lexer.Token.INDENT)
                self._skip_newlines()
                while self.peek()[0] is not lexer.Token.DEDENT:
                    else_body.append(self.parse_stmt())
                    self._skip_newlines()
                self.expect(lexer.Token.DEDENT)
        return If(cond=cond, then_body=then_body, else_body=else_body)

    def parse_while(self):
        self.expect(lexer.Token.WORD)  # dopóki
        cond = self.parse_expr()
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return While(cond=cond, body=body)

    def parse_func_def(self):
        self.expect(lexer.Token.WORD)  # aby
        name_tok = self.expect(lexer.Token.WORD)
        params = []
        while self.peek() and self.peek()[0] not in (lexer.Token.COLON, lexer.Token.ARROW):
            params.append(self.parse_param())
        return_type = None
        if self.peek() and self.peek()[0] is lexer.Token.ARROW:
            self.advance()
            return_type = canonical(self.expect(lexer.Token.WORD))
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return FunctionDef(name=canonical(name_tok), params=params, body=body, return_type=return_type)

    def parse_struct_def(self):
        self.expect(lexer.Token.WORD)  # definicja
        name_tok = self.expect(lexer.Token.WORD)
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        fields = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            fields.append(self.parse_field())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return StructDef(name=canonical(name_tok), fields=fields)

    def parse_field(self):
        name_tok = self.expect(lexer.Token.WORD)
        self.expect(lexer.Token.LPAREN)
        type_ = canonical(self.expect(lexer.Token.WORD))
        self.expect(lexer.Token.RPAREN)
        return Field(name=canonical(name_tok), type=type_)

    def parse_param(self):
        prep = None
        if self._is_prep(self.peek()):
            prep = canonical(self.advance())
        name_tok = self.expect(lexer.Token.WORD)
        type_ = None
        if self.peek() and self.peek()[0] is lexer.Token.LPAREN:
            self.advance()
            type_ = canonical(self.expect(lexer.Token.WORD))
            self.expect(lexer.Token.RPAREN)
        return Param(
            prep=prep,
            name=canonical(name_tok),
            case=self._case_of(name_tok),
            surface=name_tok[1],
            type=type_,
        )

    def parse_phrase(self):
        head_tok = self.expect(lexer.Token.WORD)
        head = Word(
            prep=None,
            value=canonical(head_tok),
            case=self._case_of(head_tok),
        )
        words = [head]
        while self._is_word_start(self.peek()):
            words.append(self.parse_simple_word())
        return Phrase(words=words)

    def _is_word_start(self, t):
        if t is None:
            return False
        if self._is_logical_op(t):
            return False
        return t[0] in (
            lexer.Token.NUMBER,
            lexer.Token.TEXT,
            lexer.Token.WORD,
            lexer.Token.LPAREN,
        )

    def parse_simple_word(self):
        prep = None
        t = self.peek()
        if self._is_prep(t):
            nxt = self.peek(1)
            if nxt and nxt[0] in (
                lexer.Token.NUMBER,
                lexer.Token.TEXT,
                lexer.Token.WORD,
                lexer.Token.LPAREN,
            ):
                prep = canonical(self.advance())
        case = None
        nxt = self.peek()
        if nxt and nxt[0] is lexer.Token.WORD:
            case = self._case_of(nxt)
        value = self.parse_simple_value()
        return Word(prep=prep, value=value, case=case)

    def parse_simple_value(self):
        t = self.peek()
        if t is None:
            raise SyntaxError("Unexpected end of input in word")
        if t[0] is lexer.Token.NUMBER:
            return IntLit(self.advance()[1])
        if t[0] is lexer.Token.TEXT:
            return StrLit(self.advance()[1])
        if t[0] is lexer.Token.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(lexer.Token.RPAREN)
            return expr
        if t[0] is lexer.Token.WORD:
            return canonical(self.advance())
        raise SyntaxError(f"Unexpected token in word value: {t}")

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.peek() and self._is_logical_op(self.peek()) and canonical(self.peek()) == ("lub",):
            self.advance()
            left = Or(left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.peek() and self._is_logical_op(self.peek()) and canonical(self.peek()) == ("i",):
            self.advance()
            left = And(left, self.parse_not())
        return left

    def parse_not(self):
        if self.peek() and self._is_logical_op(self.peek()) and canonical(self.peek()) == ("nie",):
            self.advance()
            return Not(self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_arith()
        while self.peek() and self.peek()[0] is lexer.Token.BIN_OP and self.peek()[1] in ("<", ">", "<=", ">=", "!=", "="):
            op = self.advance()[1]
            left = BinOp(op, left, self.parse_arith())
        return left

    def parse_arith(self):
        left = self.parse_term()
        while self.peek() and self.peek()[0] is lexer.Token.BIN_OP and self.peek()[1] in ("+", "-"):
            op = self.advance()[1]
            left = BinOp(op, left, self.parse_term())
        return left

    def parse_term(self):
        left = self.parse_factor()
        while self.peek() and self.peek()[0] is lexer.Token.BIN_OP and self.peek()[1] in ("*", "/", "%"):
            op = self.advance()[1]
            left = BinOp(op, left, self.parse_factor())
        return left

    def parse_factor(self):
        t = self.peek()
        if t and t[0] is lexer.Token.BIN_OP and t[1] in ("+", "-"):
            op = self.advance()[1]
            return UnaryOp(op, self.parse_factor())
        return self.parse_primary()

    def parse_primary(self):
        t = self.peek()
        if t is None:
            raise SyntaxError("Unexpected end of input in expr")
        if t[0] is lexer.Token.NUMBER:
            return IntLit(self.advance()[1])
        if t[0] is lexer.Token.TEXT:
            return StrLit(self.advance()[1])
        if t[0] is lexer.Token.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(lexer.Token.RPAREN)
            return expr
        if t[0] is lexer.Token.WORD:
            return self.parse_phrase()
        raise SyntaxError(f"Unexpected token in expr: {t}")


def parse(tokens, preps=None):
    return Parser(tokens, preps).parse_module()
