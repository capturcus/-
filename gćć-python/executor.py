import ast_nodes as ast
from dataclasses import dataclass, field

BUILTIN_FUNCTIONS = [
    ([("wypisać",)], lambda args: print(args[0].value)),
    ([("konwertować",)], lambda args: RuntimeValue(value=str(args[0].value), type="Tekst")),
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
    if isinstance(expr_node, ast.Identifier):
        return scope.variable_value(expr_node)
    if isinstance(expr_node, ast.FunctionCall):
        evaluated_params = [execute_expression(expr.value, scope) for expr in expr_node.params]
        return execute_function(expr_node.name.lemmas_set, evaluated_params)
    if isinstance(expr_node, ast.BinOp):
        left = execute_expression(expr_node.left, scope)
        right = execute_expression(expr_node.right, scope)
        fn, result_type = BIN_OPS[expr_node.op]
        return RuntimeValue(value=fn(left.value, right.value), type=result_type)

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
