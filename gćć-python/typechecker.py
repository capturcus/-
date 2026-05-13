import ast_nodes as ast


def resolve_module(node):
    print("Module")
    for decl in node.body:
        if isinstance(decl, ast.FunctionDef):
            resolve_function_def(decl)


def resolve_function_def(node):
    print("FunctionDef")
    for stmt in node.body:
        resolve_statement(stmt)


def resolve_statement(node):
    if isinstance(node, ast.Assignment):
        resolve_assignment(node)
    if isinstance(node, ast.If):
        resolve_if(node)
    if isinstance(node, ast.While):
        resolve_while(node)
    if isinstance(node, ast.For):
        resolve_for(node)
    if isinstance(node, ast.Return):
        resolve_return(node)
    resolve_expression(node)


def resolve_expression(node):
    if isinstance(node, ast.BinOp):
        resolve_bin_op(node)
    if isinstance(node, ast.UnaryOp):
        resolve_unary_op(node)
    if isinstance(node, ast.Not):
        resolve_not(node)
    if isinstance(node, ast.And):
        resolve_and(node)
    if isinstance(node, ast.Or):
        resolve_or(node)
    if isinstance(node, ast.FunctionCall):
        resolve_function_call(node)
    if isinstance(node, ast.GetterChain):
        resolve_getter_chain(node)
    if isinstance(node, ast.Subscript):
        resolve_subscript(node)
    if isinstance(node, ast.StructCreation):
        resolve_struct_creation(node)
    if isinstance(node, ast.StructArg):
        resolve_struct_arg(node)
    if isinstance(node, ast.Identifier):
        resolve_identifier(node)

def resolve_assignment(node):
    print("Assignment")
    resolve_expression(node.target.resolved)
    resolve_expression(node.value.resolved)
    # # target to krotka — element pojedynczy lub łańcuch getterów
    # if isinstance(node.target, tuple):
    #     for t in node.target:
    #         check(t)
    # else:
    #     check(node.target)
    # check(node.value)


def resolve_bin_op(node):
    print("BinOp")
    resolve_expression(node.left)
    resolve_expression(node.right)


def resolve_unary_op(node):
    print("UnaryOp")
    resolve_expression(node.operand)


def resolve_if(node):
    print("If")
    resolve_expression(node.cond)
    for stmt in node.then_body:
        resolve_statement(stmt)
    for stmt in node.else_body:
        resolve_statement(stmt)


def resolve_while(node):
    print("While")
    resolve_expression(node.cond)
    for stmt in node.body:
        resolve_statement(stmt)


def resolve_for(node):
    print("For")
    # node.var
    resolve_expression(node.collection)
    for stmt in node.body:
        resolve_statement(stmt)


def resolve_return(node):
    print("Return")
    if node.value is not None:
        resolve_expression(node.value)


def resolve_not(node):
    print("Not")
    resolve_expression(node.operand)


def resolve_and(node):
    print("And")
    resolve_expression(node.left)
    resolve_expression(node.right)


def resolve_or(node):
    print("Or")
    resolve_expression(node.left)
    resolve_expression(node.right)


def resolve_function_call(node):
    print("FunctionCall")
    for p in node.params:
        resolve_expression(p)


def resolve_getter_chain(node):
    print("GetterChain", node)


def resolve_subscript(node):
    print("Subscript")
    resolve_expression(node.target)
    resolve_expression(node.index)


def resolve_struct_creation(node):
    print("StructCreation")
    for a in node.args:
        resolve_expression(a)


def resolve_struct_arg(node):
    print("StructArg")
    if node.value is not None:
        resolve_expression(node.value)


def resolve_identifier(node):
    print("Identifier", node)


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