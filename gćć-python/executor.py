import ast_nodes as ast
from dataclasses import dataclass, field

def _tekst(rv):
    if rv.type == "Przełącznik":
        return "prawda" if rv.value else "fałsz"
    return str(rv.value)

BUILTIN_FUNCTIONS = [
    ([("wypisać",)], lambda args: print(args[0].value)),
    ([("konwertować",)], lambda args: RuntimeValue(value=_tekst(args[0]), type="Tekst")),
]

# op → (funkcja, typ wyniku); semantyka jak w typechecker.resolve_bin_op
BIN_OPS = {
    "+": (lambda a, b: a + b, "Liczba"),
    "-": (lambda a, b: a - b, "Liczba"),
    "*": (lambda a, b: a * b, "Liczba"),
    "<": (lambda a, b: a < b, "Przełącznik"),
    ">": (lambda a, b: a > b, "Przełącznik"),
    "<=": (lambda a, b: a <= b, "Przełącznik"),
    ">=": (lambda a, b: a >= b, "Przełącznik"),
    "=": (lambda a, b: a == b, "Przełącznik"),
    "!=": (lambda a, b: a != b, "Przełącznik"),
}

@dataclass
class RuntimeValue:
    value: any
    type: str

@dataclass
class RuntimeScope:
    vars: list = field(default_factory=list)

    def variable_value(self, identifier):
        for param, value in self.vars:
            if any(ast.scope_key_matches(a, b)
                   for a in identifier.scope_keys
                   for b in param.name.scope_keys):
                return value
        raise RuntimeError(f"var not found {identifier.surface}")

def execute_expression(expr_node, scope):
    if isinstance(expr_node, ast.StrLit):
        return RuntimeValue(value=str(expr_node.value), type="Tekst")
    if isinstance(expr_node, ast.IntLit):
        return RuntimeValue(value=int(expr_node.value), type="Liczba")
    if isinstance(expr_node, ast.BoolLit):
        return RuntimeValue(value=expr_node.value, type="Przełącznik")
    if isinstance(expr_node, ast.Identifier):
        return scope.variable_value(expr_node)
    if isinstance(expr_node, ast.FunctionCall):
        evaluated_params = [execute_expression(expr.value, scope) for expr in expr_node.params]
        return execute_function(expr_node.name.lemmas_set, evaluated_params)
    if isinstance(expr_node, ast.FunctionRef):
        return RuntimeValue(value=expr_node.key, type="Funkcja")
    if isinstance(expr_node, ast.Apply):
        fn = execute_expression(expr_node.fn, scope)
        args = [execute_expression(w.value, scope) for w in expr_node.args]
        return execute_function([fn.value], args)
    if isinstance(expr_node, ast.BinOp):
        left = execute_expression(expr_node.left, scope)
        right = execute_expression(expr_node.right, scope)
        fn, result_type = BIN_OPS[expr_node.op]
        return RuntimeValue(value=fn(left.value, right.value), type=result_type)
    if isinstance(expr_node, ast.UnaryOp):
        operand = execute_expression(expr_node.operand, scope)
        value = operand.value if expr_node.op == "+" else -operand.value
        return RuntimeValue(value=value, type="Liczba")
    if isinstance(expr_node, ast.Not):
        operand = execute_expression(expr_node.operand, scope)
        return RuntimeValue(value=not operand.value, type="Przełącznik")
    if isinstance(expr_node, ast.And):
        left = execute_expression(expr_node.left, scope)
        right = execute_expression(expr_node.right, scope)
        return RuntimeValue(value=left.value and right.value, type="Przełącznik")
    if isinstance(expr_node, ast.Or):
        left = execute_expression(expr_node.left, scope)
        right = execute_expression(expr_node.right, scope)
        return RuntimeValue(value=left.value or right.value, type="Przełącznik")

def execute_function(function_lemmas, args):
    for f in BUILTIN_FUNCTIONS:
        for function_lemma in function_lemmas:
            if function_lemma in f[0]:
                return f[1](args)
    global module_funcs
    function_node = None
    for f in module_funcs:
        for function_lemma in function_lemmas:
            if function_lemma in f.name.lemmas_set:
                function_node = f
    if function_node is None:
        raise RuntimeError(f"error: funkcja {function_lemmas} nie istnieje")
    scope = RuntimeScope()
    scope.vars = [(name, value) for name, value in zip(function_node.params, args)]
    for stmt in function_node.body:
        if isinstance(stmt, ast.Phrase):
            stmt = stmt.resolved
        if isinstance(stmt, ast.FunctionCall):
            evaluated_params = [execute_expression(expr.value, scope) for expr in stmt.params]
            execute_function(stmt.name.lemmas_set, evaluated_params)
        if isinstance(stmt, ast.Return):
            return execute_expression(stmt.value.resolved, scope)

def execute(module_node):
    global module_funcs
    module_funcs = [node for node in module_node.body if isinstance(node, ast.FunctionDef)]
    execute_function([("działać",)], [])
