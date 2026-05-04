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
class Var:
    name: tuple


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
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def advance(self):
        t = self.peek()
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.advance()
        if t is None or t[0] is not kind:
            raise SyntaxError(f"Expected {kind}, got {t}")
        return t

    def parse_module(self):
        body = []
        while self.peek() is not None:
            body.append(self.parse_stmt())
        return Module(body)

    def parse_stmt(self):
        t = self.peek()
        if t[0] is lexer.Token.WORD and canonical(t) == ("aby",):
            return self.parse_func_def()
        if t[0] is lexer.Token.WORD and canonical(t) == ("jeśli",):
            return self.parse_if()
        if t[0] is lexer.Token.WORD and canonical(t) == ("dopóki",):
            return self.parse_while()
        if t[0] is lexer.Token.WORD and canonical(t) == ("stop",):
            self.advance()
            return Break()
        return self.parse_assignment()

    def parse_if(self):
        self.expect(lexer.Token.WORD)  # jeśli
        cond = self.parse_expr()
        self.expect(lexer.Token.COLON)
        self.expect(lexer.Token.INDENT)
        then_body = []
        while self.peek()[0] is not lexer.Token.DEDENT:
            then_body.append(self.parse_stmt())
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
                self.expect(lexer.Token.INDENT)
                while self.peek()[0] is not lexer.Token.DEDENT:
                    else_body.append(self.parse_stmt())
                self.expect(lexer.Token.DEDENT)
        return If(cond=cond, then_body=then_body, else_body=else_body)

    def parse_while(self):
        self.expect(lexer.Token.WORD)  # dopóki
        cond = self.parse_expr()
        self.expect(lexer.Token.COLON)
        self.expect(lexer.Token.INDENT)
        body = []
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
        self.expect(lexer.Token.DEDENT)
        return While(cond=cond, body=body)

    def parse_func_def(self):
        self.expect(lexer.Token.WORD)
        name_tok = self.expect(lexer.Token.WORD)
        self.expect(lexer.Token.COLON)
        self.expect(lexer.Token.INDENT)
        body = []
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
        self.expect(lexer.Token.DEDENT)
        return FunctionDef(name=canonical(name_tok), params=[], body=body)

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
        if t and t[0] is lexer.Token.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(lexer.Token.RPAREN)
            return expr
        t = self.advance()
        if t is None:
            raise SyntaxError("Unexpected end of input in expr")
        if t[0] is lexer.Token.NUMBER:
            return IntLit(t[1])
        if t[0] is lexer.Token.TEXT:
            return StrLit(t[1])
        if t[0] is lexer.Token.WORD:
            return Var(canonical(t))
        raise SyntaxError(f"Unexpected token in expr: {t}")


def parse(tokens):
    return Parser(tokens).parse_module()
