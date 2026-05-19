import ast_nodes as ast
import re

last_type = 0
type_regex = re.compile(r"t[0-9]+")
def new_type():
    global last_type
    ret = "t"+str(last_type)
    last_type += 1
    return ret

class Scope:
    types: dict = {}

    def unify(self, t0, t1):
        if len(t0) != len(t1):
            print(f"types have wrong kind {t0} {t1} {len(t0)} {len(t1)}")
            raise
        global type_regex
        result_type = []
        for tt0, tt1 in zip(t0, t1):
            if not type_regex.match(tt0) and not type_regex.match(tt1):
                print(f"could not match types lmao: {tt0} {tt1}")
                raise
            concrete = tt1 if type_regex.match(tt0) else tt0
            result_type.append(concrete)
        for k in self.types:
            if self.types[k] == t0 or self.types[k] == t1:
                self.types[k] = concrete

def resolve_module(node):
    print("Module")
    scope = Scope()
    for decl in node.body:
        if isinstance(decl, ast.FunctionDef):
            resolve_function_def(decl, scope)
    print(scope.types)


def resolve_function_def(node, scope):
    print("FunctionDef")
    for stmt in node.body:
        resolve_statement(stmt, scope)


def resolve_statement(node, scope):
    if isinstance(node, ast.Assignment):
        resolve_assignment(node, scope)
    if isinstance(node, ast.If):
        resolve_if(node, scope)
    if isinstance(node, ast.While):
        resolve_while(node, scope)
    if isinstance(node, ast.For):
        resolve_for(node, scope)
    if isinstance(node, ast.Return):
        resolve_return(node, scope)
    resolve_expression(node, scope)


def resolve_expression(node, scope):
    if isinstance(node, ast.BinOp):
        return resolve_bin_op(node, scope)
    if isinstance(node, ast.UnaryOp):
        return resolve_unary_op(node, scope)
    if isinstance(node, ast.Not):
        return resolve_not(node, scope)
    if isinstance(node, ast.And):
        return resolve_and(node, scope)
    if isinstance(node, ast.Or):
        return resolve_or(node, scope)
    if isinstance(node, ast.FunctionCall):
        return resolve_function_call(node, scope)
    if isinstance(node, ast.GetterChain):
        return resolve_getter_chain(node, scope)
    if isinstance(node, ast.Subscript):
        return resolve_subscript(node, scope)
    if isinstance(node, ast.StructCreation):
        return resolve_struct_creation(node, scope)
    if isinstance(node, ast.StructArg):
        return resolve_struct_arg(node, scope)
    if isinstance(node, ast.Identifier):
        return resolve_identifier(node, scope)
    if isinstance(node, ast.IntLit):
        print("IntLit")
        return ["number"]
    if isinstance(node, ast.StrLit):
        print("StrLit")
        return ["string"]

def resolve_assignment(node, scope):
    print("Assignment")
    target_type = resolve_expression(node.target.resolved, scope)
    value_type = resolve_expression(node.value.resolved, scope)
    scope.unify(target_type, value_type)
    # # target to krotka — element pojedynczy lub łańcuch getterów
    # if isinstance(node.target, tuple):
    #     for t in node.target:
    #         check(t)
    # else:
    #     check(node.target)
    # check(node.value)


def resolve_bin_op(node, scope):
    print("BinOp")
    resolve_expression(node.left, scope)
    resolve_expression(node.right, scope)


def resolve_unary_op(node, scope):
    print("UnaryOp")
    resolve_expression(node.operand, scope)


def resolve_if(node, scope):
    print("If")
    resolve_expression(node.cond, scope)
    for stmt in node.then_body:
        resolve_statement(stmt, scope)
    for stmt in node.else_body:
        resolve_statement(stmt, scope)


def resolve_while(node, scope):
    print("While")
    resolve_expression(node.cond, scope)
    for stmt in node.body:
        resolve_statement(stmt, scope)


def resolve_for(node, scope):
    print("For")
    # node.var
    resolve_expression(node.collection, scope)
    for stmt in node.body:
        resolve_statement(stmt, scope)


def resolve_return(node, scope):
    print("Return")
    if node.value is not None:
        resolve_expression(node.value, scope)


def resolve_not(node, scope):
    print("Not")
    resolve_expression(node.operand, scope)


def resolve_and(node, scope):
    print("And")
    resolve_expression(node.left, scope)
    resolve_expression(node.right, scope)


def resolve_or(node, scope):
    print("Or")
    resolve_expression(node.left, scope)
    resolve_expression(node.right, scope)


def resolve_function_call(node, scope):
    print("FunctionCall")
    for p in node.params:
        resolve_expression(p, scope)


def resolve_getter_chain(node, scope):
    print("GetterChain", node)


def resolve_subscript(node, scope):
    print("Subscript")
    resolve_expression(node.target, scope)
    resolve_expression(node.index, scope)


def resolve_struct_creation(node, scope):
    print("StructCreation")
    for a in node.args:
        resolve_expression(a, scope)


def resolve_struct_arg(node, scope):
    print("StructArg")
    if node.value is not None:
        resolve_expression(node.value, scope)


def resolve_identifier(node, scope):
    new_t = new_type()
    lemmas = node.variants[0].lemmas
    scope.types[lemmas] = [new_t]
    print("Identifier")
    return [new_t]


# _DISPATCH = {
#     ast.Module: resolve_module,
#     ast.FunctionDef: resolve_function_def,
#     ast.ExternFunctionDef: resolve_extern_function_def,
#     ast.Param: resolve_param,
#     ast.StructDef: resolve_struct_def,
#     ast.Field: resolve_field,
#     ast.Phrase: resolve_phrase,
#     ast.Word: resolve_word,
#     ast.Assignment: resolve_assignment,
#     ast.IntLit: resolve_int_lit,
#     ast.StrLit: resolve_str_lit,
#     ast.BinOp: resolve_bin_op,
#     ast.UnaryOp: resolve_unary_op,
#     ast.If: resolve_if,
#     ast.While: resolve_while,
#     ast.For: resolve_for,
#     ast.Break: resolve_break,
#     ast.Continue: resolve_continue,
#     ast.Return: resolve_return,
#     ast.Not: resolve_not,
#     ast.And: resolve_and,
#     ast.Or: resolve_or,
#     ast.FunctionCall: resolve_function_call,
#     ast.GetterChain: resolve_getter_chain,
#     ast.Subscript: resolve_subscript,
#     ast.StructCreation: resolve_struct_creation,
#     ast.StructArg: resolve_struct_arg,
#     ast.Identifier: resolve_identifier,
# }

# statements
#     ast.Assignment: resolve_assignment,
#     ast.If: resolve_if,
#     ast.While: resolve_while,
#     ast.For: resolve_for,
#     ast.Return: resolve_return,


# definitions
#     ast.FunctionDef: resolve_function_def,
#     ast.ExternFunctionDef: resolve_extern_function_def,
#     ast.StructDef: resolve_struct_def,

# expressions
#     ast.BinOp: resolve_bin_op,
#     ast.UnaryOp: resolve_unary_op,
#     ast.Not: resolve_not,
#     ast.And: resolve_and,
#     ast.Or: resolve_or,
#     ast.FunctionCall: resolve_function_call,
#     ast.GetterChain: resolve_getter_chain,
#     ast.Subscript: resolve_subscript,
#     ast.StructCreation: resolve_struct_creation,
#     ast.StructArg: resolve_struct_arg,
#     ast.Identifier: resolve_identifier,
# }