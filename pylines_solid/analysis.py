import ast
import collections.abc
import types
import typing

from pylines_solid.diagnostics import Diagnostic
from pylines_solid.dispatch import check_dispatch

type MethodDefinition = ast.FunctionDef | ast.AsyncFunctionDef
type ScopeBindings = collections.abc.Mapping[str, str | None]

CLIENT_FACTORIES: typing.Final = frozenset(
    {
        "httpx.Client",
        "httpx.AsyncClient",
        "aiohttp.ClientSession",
        "asyncpg.connect",
        "asyncpg.create_pool",
        "aiokafka.connect",
        "aiokafka.AIOKafkaProducer",
        "aiokafka.AIOKafkaConsumer",
        "redis.Redis",
        "redis.StrictRedis",
        "redis.asyncio.Redis",
        "psycopg.connect",
        "psycopg2.connect",
        "sqlalchemy.create_engine",
        "sqlalchemy.ext.asyncio.create_async_engine",
    },
)
ABSTRACT_DECORATORS: typing.Final = frozenset({"abc.abstractmethod", "abc.abstractproperty"})
PROTOCOL_BASES: typing.Final = frozenset({"typing.Protocol", "typing_extensions.Protocol"})


def collect_scope_nodes(source_nodes: collections.abc.Iterable[ast.AST]) -> collections.abc.Iterator[ast.AST]:
    for one_source_node in source_nodes:
        yield one_source_node
        if not isinstance(one_source_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from collect_scope_nodes(ast.iter_child_nodes(one_source_node))


def resolve_imported_alias(
    import_statement: ast.Import | ast.ImportFrom, imported_alias: ast.alias
) -> tuple[str, str | None]:
    if isinstance(import_statement, ast.Import):
        binding_name: typing.Final = imported_alias.asname or imported_alias.name.split(".")[0]
        return binding_name, imported_alias.name if imported_alias.asname else binding_name
    return (
        imported_alias.asname or imported_alias.name,
        f"{import_statement.module}.{imported_alias.name}" if import_statement.level == 0 else None,
    )


def collect_shadowed_names(scope_nodes: collections.abc.Iterable[ast.AST]) -> collections.abc.Iterator[str]:
    for one_source_node in scope_nodes:
        if isinstance(one_source_node, ast.Name) and isinstance(one_source_node.ctx, (ast.Store, ast.Del)):
            yield one_source_node.id
        elif (
            isinstance(
                one_source_node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar),
            )
            and one_source_node.name
        ):
            yield one_source_node.name
        elif isinstance(one_source_node, ast.MatchMapping) and one_source_node.rest:
            yield one_source_node.rest


def collect_bindings(
    source_nodes: collections.abc.Iterable[ast.AST],
    parent_bindings: ScopeBindings,
    *,
    method_arguments: ast.arguments | None = None,
) -> ScopeBindings:
    scope_nodes: typing.Final = tuple(collect_scope_nodes(source_nodes))
    scope_bindings: typing.Final = dict(parent_bindings)
    imported_names: typing.Final[dict[str, str | None]] = {}
    for one_source_node in scope_nodes:
        if not isinstance(one_source_node, (ast.Import, ast.ImportFrom)):
            continue
        for one_imported_alias in one_source_node.names:
            if one_imported_alias.name == "*":
                return types.MappingProxyType(dict.fromkeys((*scope_bindings, *imported_names, "NotImplementedError")))
            binding_name, imported_name = resolve_imported_alias(one_source_node, one_imported_alias)
            imported_names[binding_name] = (
                imported_name if imported_names.get(binding_name, imported_name) == imported_name else None
            )
    scope_bindings.update(imported_names)
    scope_bindings.update(dict.fromkeys(collect_shadowed_names(scope_nodes)))
    if method_arguments is not None:
        scope_bindings.update(
            {
                one_argument_node.arg: None
                for one_argument_node in (
                    *method_arguments.posonlyargs,
                    *method_arguments.args,
                    *method_arguments.kwonlyargs,
                    method_arguments.vararg,
                    method_arguments.kwarg,
                )
                if one_argument_node is not None
            },
        )
    return types.MappingProxyType(scope_bindings)


def resolve_reference(expression_node: ast.AST, scope_bindings: ScopeBindings) -> str | None:
    if isinstance(expression_node, ast.Name):
        return scope_bindings.get(expression_node.id)
    if isinstance(expression_node, ast.Attribute):
        parent_name: typing.Final = resolve_reference(expression_node.value, scope_bindings)
        return f"{parent_name}.{expression_node.attr}" if parent_name else None
    if isinstance(expression_node, ast.Subscript):
        return resolve_reference(expression_node.value, scope_bindings)
    return None


def check_abstract(
    method_definition: MethodDefinition, class_definition: ast.ClassDef, global_bindings: ScopeBindings, /
) -> bool:
    decorator_bindings: typing.Final = collect_bindings(
        class_definition.body[: class_definition.body.index(method_definition)], global_bindings
    )
    return any(
        resolve_reference(one_decorator_node, decorator_bindings) in ABSTRACT_DECORATORS
        for one_decorator_node in method_definition.decorator_list
    )


def check_protocol(class_definition: ast.ClassDef, global_bindings: ScopeBindings) -> bool:
    return any(
        resolve_reference(one_base_node, global_bindings) in PROTOCOL_BASES for one_base_node in class_definition.bases
    )


def find_refusal(method_definition: MethodDefinition, method_bindings: ScopeBindings) -> ast.Raise | None:
    body_statements: typing.Final = [
        one_statement_node
        for one_statement_node in method_definition.body
        if not (
            isinstance(one_statement_node, ast.Expr)
            and isinstance(one_statement_node.value, ast.Constant)
            and isinstance(one_statement_node.value.value, str)
        )
    ]
    if len(body_statements) != 1 or not isinstance(body_statements[0], ast.Raise):
        return None
    raise_statement: typing.Final = body_statements[0]
    exception_node: typing.Final = (
        raise_statement.exc.func if isinstance(raise_statement.exc, ast.Call) else raise_statement.exc
    )
    if exception_node is None:
        return None
    if (
        isinstance(exception_node, ast.Name)
        and exception_node.id == "NotImplementedError"
        and exception_node.id not in method_bindings
    ) or resolve_reference(exception_node, method_bindings) == "builtins.NotImplementedError":
        return raise_statement
    return None


def find_inherited_method(
    class_definition: ast.ClassDef,
    method_name: str,
    module_classes: collections.abc.Mapping[str, ast.ClassDef],
    visited_classes: frozenset[str] = frozenset(),
    /,
) -> tuple[ast.ClassDef, MethodDefinition] | None:
    if class_definition.name in visited_classes or len(class_definition.bases) != 1:
        return None
    parent_expression: typing.Final = class_definition.bases[0]
    if not isinstance(parent_expression, ast.Name):
        return None
    parent_class: typing.Final = module_classes.get(parent_expression.id)
    if parent_class is None:
        return None
    for one_parent_statement in parent_class.body:
        if (
            isinstance(one_parent_statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and one_parent_statement.name == method_name
        ):
            return parent_class, one_parent_statement
    return find_inherited_method(
        parent_class,
        method_name,
        module_classes,
        visited_classes | {class_definition.name},
    )


def check_method(
    *,
    class_definition: ast.ClassDef,
    method_definition: MethodDefinition,
    module_classes: collections.abc.Mapping[str, ast.ClassDef],
    global_bindings: ScopeBindings,
) -> collections.abc.Iterator[Diagnostic]:
    method_bindings: typing.Final = collect_bindings(
        method_definition.body,
        global_bindings,
        method_arguments=method_definition.args,
    )
    refused_statement: typing.Final = find_refusal(method_definition, method_bindings)
    if (
        refused_statement is not None
        and not check_protocol(class_definition, global_bindings)
        and not check_abstract(method_definition, class_definition, global_bindings)
    ):
        parent_declaration: typing.Final = find_inherited_method(
            class_definition, method_definition.name, module_classes
        )
        overrides_behavior: typing.Final = (
            parent_declaration is not None
            and not check_protocol(parent_declaration[0], global_bindings)
            and not check_abstract(parent_declaration[1], parent_declaration[0], global_bindings)
            and find_refusal(
                parent_declaration[1],
                collect_bindings(
                    parent_declaration[1].body, global_bindings, method_arguments=parent_declaration[1].args
                ),
            )
            is None
        )
        yield Diagnostic(
            line_number=refused_statement.lineno,
            column_number=refused_statement.col_offset + 1,
            rule_code="PLS001" if overrides_behavior else "PLS002",
            message_text=(
                "[LSP] Possible violation: subtype rejects inherited behavior; "
                "preserve the base contract or split the hierarchy."
                if overrides_behavior
                else "[ISP] Possible violation: concrete method rejects a capability; "
                "narrow the interface or declare it abstract."
            ),
        )
    for one_source_node in collect_scope_nodes(method_definition.body):
        if (
            isinstance(one_source_node, ast.Call)
            and resolve_reference(one_source_node.func, method_bindings) in CLIENT_FACTORIES
        ):
            yield Diagnostic(
                line_number=one_source_node.lineno,
                column_number=one_source_node.col_offset + 1,
                rule_code="PLS003",
                message_text=(
                    "[SRP/DIP] Possible violation: method owns infrastructure setup; "
                    "separate setup from behavior and inject the client."
                ),
            )


def check_source(source_text: str, source_name: str) -> list[Diagnostic]:
    syntax_tree: typing.Final = ast.parse(source_text, filename=source_name)
    global_bindings: typing.Final = collect_bindings(syntax_tree.body, {})
    module_classes: typing.Final = {
        one_statement_node.name: one_statement_node
        for one_statement_node in syntax_tree.body
        if isinstance(one_statement_node, ast.ClassDef)
    }
    diagnostics_found: typing.Final = list(check_dispatch(syntax_tree))
    diagnostics_found.extend(
        one_diagnostic
        for one_class_definition in module_classes.values()
        for one_method_definition in one_class_definition.body
        if isinstance(one_method_definition, (ast.FunctionDef, ast.AsyncFunctionDef))
        for one_diagnostic in check_method(
            class_definition=one_class_definition,
            method_definition=one_method_definition,
            module_classes=module_classes,
            global_bindings=global_bindings,
        )
    )
    return diagnostics_found
