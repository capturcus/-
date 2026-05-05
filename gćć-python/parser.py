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


@dataclass
class Param:
    prep: tuple
    name: tuple
    case: str
    surface: tuple


@dataclass
class Call:
    name: tuple
    args: list


@dataclass
class Arg:
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
            if canon == ("jeśli",):
                return self.parse_if()
            if canon == ("dopóki",):
                return self.parse_while()
            if canon == ("stop",):
                self.advance()
                return Break()
            nxt = self.peek(1)
            if nxt and nxt[0] is lexer.Token.ASSIGN:
                return self.parse_assignment()
        return self.parse_expr()

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
        while self.peek() and self.peek()[0] is not lexer.Token.COLON:
            params.append(self.parse_param())
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return FunctionDef(name=canonical(name_tok), params=params, body=body)

    def parse_param(self):
        prep = None
        if self._is_prep(self.peek()):
            prep = canonical(self.advance())
        name_tok = self.expect(lexer.Token.WORD)
        return Param(
            prep=prep,
            name=canonical(name_tok),
            case=self._case_of(name_tok),
            surface=name_tok[1],
        )

    def parse_call(self):
        name_tok = self.expect(lexer.Token.WORD)
        args = []
        while self._is_arg_start(self.peek()):
            args.append(self.parse_simple_arg())
        return Call(name=canonical(name_tok), args=args)

    def _is_arg_start(self, t):
        if t is None:
            return False
        return t[0] in (
            lexer.Token.NUMBER,
            lexer.Token.TEXT,
            lexer.Token.WORD,
            lexer.Token.LPAREN,
        )

    def parse_simple_arg(self):
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
        return Arg(prep=prep, value=value, case=case)

    def parse_simple_value(self):
        t = self.peek()
        if t is None:
            raise SyntaxError("Unexpected end of input in arg")
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
            return Call(name=canonical(self.advance()), args=[])
        raise SyntaxError(f"Unexpected token in arg value: {t}")

    def parse_assignment(self):
        target_tok = self.expect(lexer.Token.WORD)
        self.expect(lexer.Token.ASSIGN)
        return Assignment(target=canonical(target_tok), value=self.parse_expr())

    def parse_expr(self):
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
            return self.parse_call()
        raise SyntaxError(f"Unexpected token in expr: {t}")


def parse(tokens, preps=None):
    return Parser(tokens, preps).parse_module()
