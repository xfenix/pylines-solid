import ast
import typing

from pylines_solid.diagnostics import Diagnostic

if typing.TYPE_CHECKING:
    import collections.abc

type DispatchRoute = tuple[str, str, str]

MINIMUM_ROUTES: typing.Final = 3


def read_reference(expression: ast.AST) -> str | None:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        parent_reference: typing.Final = read_reference(expression.value)
        if parent_reference is not None:
            return f"{parent_reference}.{expression.attr}"
    return None


def read_handler(statements: list[ast.stmt]) -> str | None:
    match statements:
        case (
            [ast.Return(value=expression)]
            | [ast.Expr(value=expression)]
            | [
                ast.Expr(value=expression),
                ast.Return(value=None),
            ]
        ):
            if isinstance(expression, ast.Await):
                expression = expression.value
            return read_reference(expression.func) if isinstance(expression, ast.Call) else None
        case _:
            return None


def read_comparison(expression: ast.expr) -> tuple[str, str] | None:
    match expression:
        case (
            ast.Compare(
                left=selector,
                ops=[ast.Eq()],
                comparators=[ast.Constant(value=str() as literal_value)],
            )
            | ast.Compare(
                left=ast.Constant(value=str() as literal_value),
                ops=[ast.Eq()],
                comparators=[selector],
            )
        ):
            selector_name: typing.Final = read_reference(selector)
            if selector_name is not None:
                return selector_name, literal_value
    return None


def collect_if_routes(branch_node: ast.If) -> list[DispatchRoute]:
    dispatch_routes: typing.Final[list[DispatchRoute]] = []
    while True:
        comparison = read_comparison(branch_node.test)
        handler_name = read_handler(branch_node.body)
        if comparison is None or handler_name is None:
            return []
        dispatch_routes.append((*comparison, handler_name))
        if len(branch_node.orelse) != 1 or not isinstance(branch_node.orelse[0], ast.If):
            return dispatch_routes
        branch_node = branch_node.orelse[0]


def collect_match_routes(branch_node: ast.Match) -> list[DispatchRoute]:
    selector_name: typing.Final = read_reference(branch_node.subject)
    if selector_name is None:
        return []
    dispatch_routes: typing.Final[list[DispatchRoute]] = []
    for one_match_case in branch_node.cases:
        if one_match_case.guard is not None:
            return []
        match one_match_case.pattern:
            case ast.MatchAs(pattern=None, name=None):
                continue
            case ast.MatchValue(value=ast.Constant(value=str() as literal_value)):
                handler_name = read_handler(one_match_case.body)
                if handler_name is None:
                    return []
                dispatch_routes.append((selector_name, literal_value, handler_name))
            case _:
                return []
    return dispatch_routes


def check_dispatch(syntax_tree: ast.Module) -> collections.abc.Iterator[Diagnostic]:
    syntax_nodes: typing.Final = tuple(ast.walk(syntax_tree))
    chained_branches: typing.Final = {
        one_source_node.orelse[0]
        for one_source_node in syntax_nodes
        if isinstance(one_source_node, ast.If)
        and len(one_source_node.orelse) == 1
        and isinstance(one_source_node.orelse[0], ast.If)
    }
    for one_source_node in syntax_nodes:
        if not isinstance(one_source_node, (ast.If, ast.Match)) or one_source_node in chained_branches:
            continue
        dispatch_routes = (
            collect_if_routes(one_source_node)
            if isinstance(one_source_node, ast.If)
            else collect_match_routes(one_source_node)
        )
        if (
            len(dispatch_routes) >= MINIMUM_ROUTES
            and len({selector_name for selector_name, _, _ in dispatch_routes}) == 1
            and len({literal_value for _, literal_value, _ in dispatch_routes}) == len(dispatch_routes)
            and len({handler_name for _, _, handler_name in dispatch_routes}) == len(dispatch_routes)
        ):
            yield Diagnostic(
                line_number=one_source_node.lineno,
                column_number=one_source_node.col_offset + 1,
                rule_code="PLS004",
                message_text=(
                    f"[OCP] Possible violation: dispatcher hardcodes {len(dispatch_routes)} handlers; "
                    "use a registry to add handlers without editing branches."
                ),
            )
