import ast_nodes as ast
import re
from dataclasses import dataclass, field

last_type = 0
type_regex = re.compile(r"t[0-9]+")

def new_type():
    global last_type
    ret = "t"+str(last_type)
    last_type += 1
    return ret

all_types = {}

def find_type(t):
    global all_types
    global type_regex
    if not type_regex.match(t):
        # concrete type
        return t
    if not t in all_types.keys():
        all_types[t] = t
        return t
    v = all_types[t]
    if v == t:
        # end of tree
        return v
    return find_type(v)

def unify_types(t0, t1):
    global type_regex
    global all_types
    ft0 = find_type(t0)
    ft1 = find_type(t1)
    if not type_regex.match(ft0) and not type_regex.match(ft1):
        if ft0 == ft1:
            return ft0
        print(f"cannot unify {ft0} with {ft1}")
        raise
    concrete, abstract = (ft0, ft1) if type_regex.match(ft1) else (ft1, ft0)
    all_types[abstract] = concrete
    return concrete

class Scope:
    def __init__(self):
        self.types = []

    def get_type(self, identifier):
        id_lemmas = set([variant.lemmas for variant in identifier.variants])
        for i in self.types:
            v = i[0]
            t = i[1]
            variable_lemmas = set([variant.lemmas for variant in v.variants])
            if id_lemmas & variable_lemmas:
                return t
        new_t = new_type()
        self.types.append((identifier, new_t))
        return new_t

@dataclass
class FunDefTypes:
    name: ast.FunctionIdentifier
    arg_types: list
    ret_type: str

fun_decls = []

def find_fdt(func_id):
    global fun_decls
    for (name, fdt) in fun_decls:
        if name.lemmas_set & func_id.lemmas_set:
            return fdt

def resolve_module(node):
    print("Module")
    global fun_decls
    fun_scopes = []
    for decl in node.body:
        if isinstance(decl, ast.FunctionDef):
            fdt = FunDefTypes(
                name=decl.name,
                arg_types=[new_type() for _ in range(len(decl.params))],
                ret_type=new_type()
            )
            i = 0
            for p in decl.params:
                if not p.type is None:
                    unify_types(fdt.arg_types[i], "".join(p.type))
                i += 1
            if not decl.return_type is None:
                unify_types(fdt.ret_type, "".join(decl.return_type))
            fun_decls.append((decl.name, fdt))
    for decl in node.body:
        if isinstance(decl, ast.FunctionDef):
            scope = Scope()
            fun_scopes.append(scope)
            resolve_function_def(decl, scope)
    for scope in fun_scopes:
        print("===")
        for i in scope.types:
            v = i[0]
            t = i[1]
            print("")
            print(v, find_type(t))


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
    if isinstance(node, ast.Phrase):
        node = node.resolved
    if isinstance(node, ast.Word):
        node = node.value
    if isinstance(node, ast.Typed):
        expr_t = resolve_expression(node.expr, scope)
        explicit_t = "".join(node.type)
        return unify_types(expr_t, explicit_t)
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
        return "Liczba"
    if isinstance(node, ast.StrLit):
        print("StrLit")
        return "Tekst"

def resolve_assignment(node, scope):
    print("Assignment")
    target_type = resolve_expression(node.target.resolved, scope)
    value_type = resolve_expression(node.value.resolved, scope)
    unify_types(target_type, value_type)
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
    fdt = find_fdt(node.name)
    for (t0, p) in zip(fdt.arg_types, node.params):
        t1 = resolve_expression(p, scope)
        unify_types(t0, t1)
    return fdt.ret_type
    # fun_scope = fun_scope_for_lemmas_set(node.name.lemmas_set)
    # fun_decl = fun_decl_for_lemmas_set(node.name.lemmas_set)
    # i = 0
    # for p in node.params:
    #     t = resolve_expression(p, scope)
    #     scope.unify_other(fun_scope, t, fun_scope.get_type(fun_decl.params[i].name))
    #     i += 1


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
    return scope.get_type(node)


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