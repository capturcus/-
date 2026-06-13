import ast_nodes as ast
from dataclasses import dataclass, field

@dataclass
class RuntimeScope:
    vars: list = field(default_factory=list)

def execute_function(function_lemma, args):
    global module_funcs
    for f in module_funcs:
        if function_lemma in f.name.lemmas_set:
            function_node = f
    print(function_node)

def execute(module_node):
    global module_funcs
    module_funcs = [node for node in module_node.body if isinstance(node, ast.FunctionDef)]
    execute_function(("działać",), [])
