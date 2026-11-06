import ast
import typing

from pylines_solid.diagnostics import Diagnostic

if typing.TYPE_CHECKING:
    import collections.abc

type DispatchRoute = tuple[str, str, str]

MINIMUM_ROUTES: typing.Final = 3
MINIMUM_SUBTYPES: typing.Final = 2
ISINSTANCE_ARGUMENTS: typing.Final = 2


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


def check_type_dispatch(
    syntax_tree: ast.Module, module_classes: dict[str, ast.ClassDef]
) -> typing.Iterator[Diagnostic]:
    """Find local subtype checks that bypass a missing base capability."""
    for one_branch_node in ast.walk(syntax_tree):
        if not isinstance(one_branch_node, ast.If) or not isinstance(one_branch_node.test, ast.BoolOp):
            continue
        if not isinstance(one_branch_node.test.op, ast.Or) or len(one_branch_node.test.values) < MINIMUM_SUBTYPES:
            continue
        type_checks = one_branch_node.test.values
        if any(
            not isinstance(one_check_node, ast.Call)
            or not isinstance(one_check_node.func, ast.Name)
            or one_check_node.func.id != "isinstance"
            or len(one_check_node.args) != ISINSTANCE_ARGUMENTS
            or one_check_node.keywords
            or not isinstance(one_check_node.args[0], ast.Name)
            or not isinstance(one_check_node.args[1], ast.Name)
            for one_check_node in type_checks
        ):
            continue
        selector_names = {
            one_argument_node.id
            for one_check_node in type_checks
            if isinstance(one_check_node, ast.Call)
            for one_argument_node in one_check_node.args[:1]
            if isinstance(one_argument_node, ast.Name)
        }
        subtype_names = {
            one_argument_node.id
            for one_check_node in type_checks
            if isinstance(one_check_node, ast.Call)
            for one_argument_node in one_check_node.args[1:2]
            if isinstance(one_argument_node, ast.Name)
        }
        if len(selector_names) != 1 or len(subtype_names) < MINIMUM_SUBTYPES:
            continue
        subtypes = [module_classes.get(one_subtype_name) for one_subtype_name in subtype_names]
        if any(
            one_subtype is None or len(one_subtype.bases) != 1 or not isinstance(one_subtype.bases[0], ast.Name)
            for one_subtype in subtypes
        ):
            continue
        base_names = {
            one_subtype.bases[0].id
            for one_subtype in subtypes
            if one_subtype is not None and isinstance(one_subtype.bases[0], ast.Name)
        }
        if len(base_names) != 1:
            continue
        base_class = module_classes.get(next(iter(base_names)))
        if base_class is None:
            continue
        base_methods = {
            one_method.name
            for one_method in base_class.body
            if isinstance(one_method, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        subtype_methods = [
            {
                one_method.name
                for one_method in one_subtype.body
                if isinstance(one_method, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for one_subtype in subtypes
            if one_subtype is not None
        ]
        shared_methods = set.intersection(*subtype_methods) - base_methods
        if any(
            isinstance(one_call_node, ast.Call)
            and isinstance(one_call_node.func, ast.Attribute)
            and isinstance(one_call_node.func.value, ast.Name)
            and one_call_node.func.value.id in selector_names
            and one_call_node.func.attr in shared_methods
            for one_statement_node in one_branch_node.body
            for one_call_node in ast.walk(one_statement_node)
        ):
            yield Diagnostic(
                line_number=one_branch_node.lineno,
                column_number=one_branch_node.col_offset + 1,
                rule_code="PLS008",
                message_text=(
                    "[OCP/LSP] Possible violation: subtype checks hide a capability missing from the base; "
                    "declare the shared contract and remove type-based dispatch."
                ),
            )
