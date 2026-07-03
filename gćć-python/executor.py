import ast_nodes as ast
from dataclasses import dataclass, field

class ErrorPropagation(Exception):
    """Gałąź-Błąd wywołania '?' — przerywa funkcję otaczającą, która
    zwraca niesiony Błąd jako swój wynik."""
    def __init__(self, value):
        self.value = value

class ReturnUnwind(Exception):
    """`zwróć` w zagnieżdżonym bloku — przerywa ciało funkcji z wartością."""
    def __init__(self, value):
        self.value = value

def _tekst(rv):
    if rv.type == "Przełącznik":
        return "prawda" if rv.value else "fałsz"
    if isinstance(rv.value, dict):
        fields = ", ".join(f"{'_'.join(k[0])}: {_tekst(v)}" for k, v in rv.value.items())
        return f"{rv.type}({fields})"
    return str(rv.value)

BUILTIN_FUNCTIONS = [
    ([("wypisać",)], lambda args: print(_tekst(args[0]))),
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
    vars: list = field(default_factory=list)  # [(scope_keys, RuntimeValue)]
    parent: object = None

    def variable_value(self, keys):
        for stored_keys, value in self.vars:
            if any(ast.scope_key_matches(a, b) for a in keys for b in stored_keys):
                return value
        if self.parent is not None:
            return self.parent.variable_value(keys)
        raise RuntimeError(f"var not found {keys}")

    def assign(self, keys, value):
        # Reasignacja tam, gdzie zmienna jest widoczna (także u przodka);
        # niewidoczna nigdzie → deklaracja w bieżącym bloku.
        scope = self
        while scope is not None:
            for i, (stored_keys, _) in enumerate(scope.vars):
                if any(ast.scope_key_matches(a, b) for a in keys for b in stored_keys):
                    scope.vars[i] = (stored_keys, value)
                    return
            scope = scope.parent
        self.vars.append((keys, value))

def execute_expression(expr_node, scope):
    if isinstance(expr_node, ast.StrLit):
        return RuntimeValue(value=str(expr_node.value), type="Tekst")
    if isinstance(expr_node, ast.IntLit):
        return RuntimeValue(value=int(expr_node.value), type="Liczba")
    if isinstance(expr_node, ast.BoolLit):
        return RuntimeValue(value=expr_node.value, type="Przełącznik")
    if isinstance(expr_node, ast.Identifier):
        return scope.variable_value(expr_node.scope_keys)
    if isinstance(expr_node, ast.FunctionCall):
        evaluated_params = [execute_expression(expr.value, scope) for expr in expr_node.params]
        return execute_function(expr_node.name.lemmas_set, evaluated_params)
    if isinstance(expr_node, ast.FunctionRef):
        return RuntimeValue(value=expr_node.key, type="Funkcja")
    if isinstance(expr_node, ast.Apply):
        fn = execute_expression(expr_node.fn, scope)
        args = [execute_expression(w.value, scope) for w in expr_node.args]
        return execute_function([fn.value], args)
    if isinstance(expr_node, ast.StructCreation):
        fields = {}
        for arg in expr_node.args:
            if arg.value is None:  # skrót `z polem` — zmienna o nazwie pola
                fields[arg.field_name] = scope.variable_value([arg.field_name])
            else:
                fields[arg.field_name] = execute_expression(arg.value, scope)
        return RuntimeValue(value=fields, type="".join(expr_node.type_name))
    if isinstance(expr_node, ast.TryCall):
        result = execute_expression(expr_node.call, scope)
        if result.type == "Błąd":
            raise ErrorPropagation(result)
        return next(iter(result.value.values()))
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
    scope.vars = [(p.name.scope_keys, value) for p, value in zip(function_node.params, args)]
    try:
        execute_block(function_node.body, scope)
    except ReturnUnwind as r:
        return r.value
    except ErrorPropagation as e:
        return e.value

def execute_block(stmts, scope):
    for stmt in stmts:
        if isinstance(stmt, ast.Phrase):
            stmt = stmt.resolved
        if isinstance(stmt, ast.FunctionCall):
            evaluated_params = [execute_expression(expr.value, scope) for expr in stmt.params]
            execute_function(stmt.name.lemmas_set, evaluated_params)
        if isinstance(stmt, ast.Assignment):
            value = execute_expression(stmt.value.resolved, scope)
            target = stmt.target.resolved
            if not isinstance(target, ast.Identifier):
                raise RuntimeError("zapis do pola (chain-LHS) jeszcze nieobsługiwany")
            scope.assign(target.scope_keys, value)
        if isinstance(stmt, ast.If):
            cond = execute_expression(stmt.cond.resolved, scope)
            branch = stmt.then_body if cond.value else stmt.else_body
            execute_block(branch, RuntimeScope(parent=scope))
        if isinstance(stmt, ast.While):
            while execute_expression(stmt.cond.resolved, scope).value:
                execute_block(stmt.body, RuntimeScope(parent=scope))
        if isinstance(stmt, ast.Return):
            raise ReturnUnwind(execute_expression(stmt.value.resolved, scope))

def execute(module_node):
    global module_funcs
    module_funcs = [node for node in module_node.body if isinstance(node, ast.FunctionDef)]
    execute_function([("działać",)], [])
