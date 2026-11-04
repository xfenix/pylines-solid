import ast
import symtable
import typing

from pylines_solid.diagnostics import Diagnostic


@typing.final
class PreserveComprehensionScopes(ast.NodeTransformer):
    @typing.override
    def generic_visit(self, source_node: ast.AST) -> ast.AST:  # noqa: COP009 -- ast.NodeTransformer callback name
        visited_node: typing.Final = super().generic_visit(source_node)
        # CPython inlines comprehensions and loses some receiver references in symtable.
        if isinstance(visited_node, (ast.ListComp, ast.SetComp)):
            return ast.GeneratorExp(
                elt=visited_node.elt.value if isinstance(visited_node.elt, ast.Starred) else visited_node.elt,
                generators=visited_node.generators,
            )
        if isinstance(visited_node, ast.DictComp):
            return ast.GeneratorExp(
                elt=ast.Tuple(
                    elts=[
                        one_element for one_element in (visited_node.key, visited_node.value) if one_element is not None
                    ],
                    ctx=ast.Load(),
                ),
                generators=visited_node.generators,
            )
        return visited_node


def collect_function_scopes(scope_table: symtable.SymbolTable) -> dict[tuple[int, str], symtable.SymbolTable]:
    function_scopes: typing.Final = (
        {(scope_table.get_lineno(), scope_table.get_name()): scope_table}
        if scope_table.get_type() == symtable.SymbolTableType.FUNCTION
        else {}
    )
    for one_child_scope in scope_table.get_children():
        function_scopes.update(collect_function_scopes(one_child_scope))
    return function_scopes


def check_receiver_reference(
    scope_table: symtable.SymbolTable, receiver_name: str, *, nested_scope: bool = False
) -> bool:
    if scope_table.get_type() == symtable.SymbolTableType.ANNOTATION:
        return False
    receiver_symbol: typing.Final = (
        scope_table.lookup(receiver_name) if receiver_name in scope_table.get_identifiers() else None
    )
    if receiver_symbol is not None:
        if scope_table.get_type() == symtable.SymbolTableType.CLASS:
            if receiver_symbol.is_free() and receiver_symbol.is_referenced():
                return True
        elif nested_scope and not receiver_symbol.is_free():
            return False
        elif receiver_symbol.is_referenced():
            return True
    return any(
        check_receiver_reference(one_child_scope, receiver_name, nested_scope=True)
        for one_child_scope in scope_table.get_children()
    )


def check_receiver(
    method_definition: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Diagnostic | None:
    positional_arguments: typing.Final = [
        *method_definition.args.posonlyargs,
        *method_definition.args.args,
    ]
    if not positional_arguments or method_definition.name.startswith("__"):
        return None
    receiver_name: typing.Final = positional_arguments[0].arg
    scope_tree: typing.Final = PreserveComprehensionScopes().visit(ast.parse(ast.unparse(method_definition)))
    method_scope: typing.Final = next(
        one_scope
        for one_scope in collect_function_scopes(
            symtable.symtable(ast.unparse(ast.fix_missing_locations(scope_tree)), "<receiver>", "exec")
        ).values()
        if one_scope.get_name() == method_definition.name
    )
    if check_receiver_reference(method_scope, receiver_name):
        return None
    return Diagnostic(
        line_number=method_definition.lineno,
        column_number=method_definition.col_offset + 1,
        rule_code="PLS006",
        message_text=(
            f"[SRP] Method body does not use its receiver '{receiver_name}'; "
            "move independent behavior to a module function or the responsible object."
        ),
    )
