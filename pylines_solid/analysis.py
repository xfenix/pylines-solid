import ast
import collections.abc
import types
import typing

from pylines_solid.diagnostics import Diagnostic
from pylines_solid.dispatch import check_dispatch, check_type_dispatch
from pylines_solid.receivers import check_receiver

type MethodDefinition = ast.FunctionDef | ast.AsyncFunctionDef
type ScopeBindings = collections.abc.Mapping[str, str | None]

INFRA_MODULE_HINTS: typing.Final = frozenset(
    {
        "http",
        "requests",
        "urllib",
        "asks",
        "treq",
        "curl",
        "niquests",
        "sql",
        "db",
        "psycopg",
        "asyncpg",
        "mysql",
        "redis",
        "mongo",
        "motor",
        "kafka",
        "amqp",
        "pika",
        "kombu",
        "boto",
        "grpc",
        "elastic",
        "opensearch",
    }
)
RESOURCE_CALL_NAMES: typing.Final = frozenset(
    {
        "client",
        "resource",
        "connect",
        "create_pool",
        "create_engine",
        "create_async_engine",
        "from_url",
        "urlopen",
        "sessionmaker",
        "secure_channel",
        "insecure_channel",
    }
)
HTTP_CALL_NAMES: typing.Final = frozenset(
    {"request", "get", "post", "put", "patch", "delete", "head", "options", "stream"}
)
RESOURCE_TYPE_NAMES: typing.Final = frozenset({"Redis", "StrictRedis", "RedisCluster", "Sentinel", "Curl"})
RESOURCE_TYPE_SUFFIXES: typing.Final = (
    "Client",
    "Session",
    "Connection",
    "Pool",
    "Producer",
    "Consumer",
    "Engine",
    "Connector",
    "Transport",
    "PoolManager",
    "ProxyManager",
)
ABSTRACT_DECORATORS: typing.Final = frozenset({"abc.abstractmethod", "abc.abstractproperty"})
PROTOCOL_BASES: typing.Final = frozenset({"typing.Protocol", "typing_extensions.Protocol"})
MINIMUM_CAPABILITIES: typing.Final = 2


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


def check_client_factory(reference_name: str | None) -> bool:
    if reference_name is None or "." not in reference_name:
        return False
    module_name, _, factory_name = reference_name.rpartition(".")
    module_segments: typing.Final = module_name.lower().split(".")
    if not any(one_hint in one_segment for one_segment in module_segments for one_hint in INFRA_MODULE_HINTS):
        return False
    if factory_name in RESOURCE_TYPE_NAMES or factory_name.endswith(RESOURCE_TYPE_SUFFIXES):
        return True
    if not factory_name.islower():
        return False
    if factory_name in RESOURCE_CALL_NAMES:
        return True
    return factory_name in HTTP_CALL_NAMES and any(
        one_hint in one_segment
        for one_segment in module_segments
        for one_hint in ("http", "requests", "urllib", "asks", "treq", "curl", "niquests")
    )


def find_dataclass_client(field_value: ast.Call, global_bindings: ScopeBindings) -> ast.expr | None:
    if check_client_factory(resolve_reference(field_value.func, global_bindings)):
        return field_value
    if resolve_reference(field_value.func, global_bindings) != "dataclasses.field":
        return None
    for one_keyword in field_value.keywords:
        if one_keyword.arg != "default_factory":
            continue
        factory_node = one_keyword.value
        if check_client_factory(resolve_reference(factory_node, global_bindings)):
            return factory_node
        if isinstance(factory_node, ast.Lambda):
            return next(
                (
                    one_call_node
                    for one_call_node in ast.walk(factory_node.body)
                    if isinstance(one_call_node, ast.Call)
                    and check_client_factory(resolve_reference(one_call_node.func, global_bindings))
                ),
                None,
            )
    return None


def check_dataclass_factory(
    class_definition: ast.ClassDef, global_bindings: ScopeBindings
) -> collections.abc.Iterator[Diagnostic]:
    if not any(
        resolve_reference(
            one_decorator.func if isinstance(one_decorator, ast.Call) else one_decorator,
            global_bindings,
        )
        == "dataclasses.dataclass"
        for one_decorator in class_definition.decorator_list
    ):
        return
    for one_statement in class_definition.body:
        field_value = one_statement.value if isinstance(one_statement, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(field_value, ast.Call):
            continue
        client_node = find_dataclass_client(field_value, global_bindings)
        if client_node is not None:
            yield Diagnostic(
                line_number=client_node.lineno,
                column_number=client_node.col_offset + 1,
                rule_code="PLS003",
                message_text=(
                    "[SRP/DIP] Possible violation: dataclass creates its infrastructure client; "
                    "inject the client or build it in the composition root."
                ),
            )


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
    parent_declaration: typing.Final = find_inherited_method(class_definition, method_definition.name, module_classes)
    refused_statement: typing.Final = find_refusal(method_definition, method_bindings)
    if (
        refused_statement is not None
        and not check_protocol(class_definition, global_bindings)
        and not check_abstract(method_definition, class_definition, global_bindings)
    ):
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
        if isinstance(one_source_node, ast.Call) and check_client_factory(
            resolve_reference(one_source_node.func, method_bindings)
        ):
            yield Diagnostic(
                line_number=one_source_node.lineno,
                column_number=one_source_node.col_offset + 1,
                rule_code="PLS003",
                message_text=(
                    "[SRP/DIP] Possible violation: method creates a client or makes a one-shot infrastructure call; "
                    "inject the client and keep setup outside this class."
                ),
            )
    if parent_declaration is not None:
        guarded_rejection: typing.Final = check_guarded_rejection(
            method_definition, parent_declaration[1], global_bindings=global_bindings
        )
        if guarded_rejection is not None:
            yield guarded_rejection


def check_local_dependency(
    class_definition: ast.ClassDef, module_classes: collections.abc.Mapping[str, ast.ClassDef]
) -> collections.abc.Iterator[Diagnostic]:
    for one_method_definition in class_definition.body:
        if not isinstance(one_method_definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        positional_arguments = [*one_method_definition.args.posonlyargs, *one_method_definition.args.args]
        if not positional_arguments:
            continue
        receiver_name = positional_arguments[0].arg
        for one_assignment_node in collect_scope_nodes(one_method_definition.body):
            if (
                not isinstance(one_assignment_node, ast.Assign)
                or len(one_assignment_node.targets) != 1
                or not isinstance(one_assignment_node.targets[0], ast.Attribute)
                or not isinstance(one_assignment_node.targets[0].value, ast.Name)
                or one_assignment_node.targets[0].value.id != receiver_name
                or not isinstance(one_assignment_node.value, ast.Call)
                or not isinstance(one_assignment_node.value.func, ast.Name)
            ):
                continue
            dependency_class = module_classes.get(one_assignment_node.value.func.id)
            if dependency_class is None or dependency_class is class_definition:
                continue
            capability_names = {
                one_member.name
                for one_member in dependency_class.body
                if isinstance(one_member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not one_member.name.startswith("__")
            }
            attribute_name = one_assignment_node.targets[0].attr
            if not capability_names or not any(
                isinstance(one_call_node, ast.Call)
                and isinstance(one_call_node.func, ast.Attribute)
                and one_call_node.func.attr in capability_names
                and isinstance(one_call_node.func.value, ast.Attribute)
                and isinstance(one_call_node.func.value.value, ast.Name)
                and one_call_node.func.value.value.id == receiver_name
                and one_call_node.func.value.attr == attribute_name
                for one_other_method in class_definition.body
                if isinstance(one_other_method, (ast.FunctionDef, ast.AsyncFunctionDef))
                and one_other_method is not one_method_definition
                for one_statement_node in one_other_method.body
                for one_call_node in collect_scope_nodes((one_statement_node,))
            ):
                continue
            yield Diagnostic(
                line_number=one_assignment_node.value.lineno,
                column_number=one_assignment_node.value.col_offset + 1,
                rule_code="PLS009",
                message_text=(
                    "[DIP] Possible violation: class creates and owns a local collaborator; "
                    "inject the dependency or define the composition root."
                ),
            )


def check_guarded_rejection(
    method_definition: MethodDefinition,
    parent_method: MethodDefinition,
    *,
    global_bindings: ScopeBindings,
) -> Diagnostic | None:
    child_arguments: typing.Final = [*method_definition.args.posonlyargs, *method_definition.args.args][1:]
    parent_arguments: typing.Final = [*parent_method.args.posonlyargs, *parent_method.args.args][1:]
    if not child_arguments or len(child_arguments) != len(parent_arguments):
        return None
    if any(
        one_child_argument.arg != one_parent_argument.arg
        or one_child_argument.annotation is None
        or one_parent_argument.annotation is None
        or ast.dump(one_child_argument.annotation) != ast.dump(one_parent_argument.annotation)
        for one_child_argument, one_parent_argument in zip(child_arguments, parent_arguments, strict=True)
    ):
        return None
    parent_statements: typing.Final = [
        one_statement
        for one_statement in parent_method.body
        if not isinstance(one_statement, ast.Expr) or not isinstance(one_statement.value, ast.Constant)
    ]
    if len(parent_statements) != 1 or not isinstance(parent_statements[0], ast.Return):
        return None
    child_bindings: typing.Final = collect_bindings(
        method_definition.body, global_bindings, method_arguments=method_definition.args
    )
    for one_branch_node in method_definition.body:
        if not isinstance(one_branch_node, ast.If) or one_branch_node.orelse or len(one_branch_node.body) != 1:
            continue
        if not isinstance(one_branch_node.body[0], ast.Raise):
            continue
        raise_statement = one_branch_node.body[0]
        exception_node = raise_statement.exc.func if isinstance(raise_statement.exc, ast.Call) else raise_statement.exc
        if exception_node is None or resolve_builtin(exception_node, child_bindings) not in {
            "builtins.ValueError",
            "builtins.TypeError",
        }:
            continue
        argument_names = {one_argument.arg for one_argument in child_arguments}
        if not any(
            isinstance(one_name_node, ast.Name) and one_name_node.id in argument_names
            for one_name_node in ast.walk(one_branch_node.test)
        ):
            continue
        return Diagnostic(
            line_number=raise_statement.lineno,
            column_number=raise_statement.col_offset + 1,
            rule_code="PLS010",
            message_text=(
                "[LSP] Possible violation: override rejects an argument accepted by the local base; "
                "preserve the base precondition."
            ),
        )
    return None


def check_interface_usage(
    syntax_tree: ast.Module,
    module_classes: collections.abc.Mapping[str, ast.ClassDef],
    *,
    global_bindings: ScopeBindings,
) -> collections.abc.Iterator[Diagnostic]:
    for one_function_node in ast.walk(syntax_tree):
        if not isinstance(one_function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body_nodes = tuple(collect_scope_nodes(one_function_node.body))
        for one_argument in (*one_function_node.args.posonlyargs, *one_function_node.args.args):
            if not isinstance(one_argument.annotation, ast.Name):
                continue
            protocol_class = module_classes.get(one_argument.annotation.id)
            if protocol_class is None or not check_protocol(protocol_class, global_bindings):
                continue
            capability_names = {
                one_member.name
                for one_member in protocol_class.body
                if isinstance(one_member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not one_member.name.startswith("_")
            }
            if len(capability_names) < MINIMUM_CAPABILITIES:
                continue
            references = [
                one_name_node
                for one_name_node in body_nodes
                if isinstance(one_name_node, ast.Name) and one_name_node.id == one_argument.arg
            ]
            capability_calls = [
                one_call_node
                for one_call_node in body_nodes
                if isinstance(one_call_node, ast.Call)
                and isinstance(one_call_node.func, ast.Attribute)
                and isinstance(one_call_node.func.value, ast.Name)
                and one_call_node.func.value.id == one_argument.arg
                and one_call_node.func.attr in capability_names
            ]
            if not capability_calls or len(references) != len(capability_calls):
                continue
            used_capabilities = {
                one_call_node.func.attr
                for one_call_node in capability_calls
                if isinstance(one_call_node.func, ast.Attribute)
            }
            if used_capabilities == capability_names:
                continue
            yield Diagnostic(
                line_number=one_argument.lineno,
                column_number=one_argument.col_offset + 1,
                rule_code="PLS011",
                message_text=(
                    "[ISP] Possible violation: client requires protocol capabilities it never calls; "
                    "accept a smaller Protocol for this client."
                ),
            )


def resolve_builtin(expression_node: ast.AST, scope_bindings: ScopeBindings) -> str | None:
    if isinstance(expression_node, ast.Name) and expression_node.id not in scope_bindings:
        return f"builtins.{expression_node.id}"
    return resolve_reference(expression_node, scope_bindings)


def check_method_responsibility(
    *,
    class_definition: ast.ClassDef,
    method_definition: MethodDefinition,
    module_classes: collections.abc.Mapping[str, ast.ClassDef],
    global_bindings: ScopeBindings,
) -> collections.abc.Iterator[Diagnostic]:
    decorator_bindings: typing.Final = collect_bindings(
        class_definition.body[: class_definition.body.index(method_definition)], global_bindings
    )
    decorator_names: typing.Final = {
        resolve_builtin(one_decorator_node, decorator_bindings)
        for one_decorator_node in method_definition.decorator_list
    }
    if "builtins.staticmethod" in decorator_names:
        yield Diagnostic(
            line_number=method_definition.lineno,
            column_number=method_definition.col_offset + 1,
            rule_code="PLS005",
            message_text="[SRP] Team rule: static methods are forbidden; move the function out of the class.",
        )
        return
    if (
        decorator_names - {"builtins.classmethod", "builtins.property"}
        or check_protocol(class_definition, global_bindings)
        or check_abstract(method_definition, class_definition, global_bindings)
        or find_inherited_method(class_definition, method_definition.name, module_classes) is not None
    ):
        return
    method_bindings: typing.Final = collect_bindings(
        method_definition.body, global_bindings, method_arguments=method_definition.args
    )
    if find_refusal(method_definition, method_bindings) is not None:
        return
    if all(
        isinstance(one_statement, ast.Pass)
        or (isinstance(one_statement, ast.Expr) and isinstance(one_statement.value, ast.Constant))
        for one_statement in method_definition.body
    ):
        return
    if any(
        isinstance(one_source_node, ast.Call)
        and (
            check_client_factory(resolve_reference(one_source_node.func, method_bindings))
            or resolve_builtin(one_source_node.func, method_bindings) == "builtins.super"
        )
        for one_source_node in collect_scope_nodes(method_definition.body)
    ):
        return
    receiver_diagnostic: typing.Final = check_receiver(method_definition)
    if receiver_diagnostic is not None:
        yield receiver_diagnostic


def check_source(source_text: str, source_name: str) -> list[Diagnostic]:
    syntax_tree: typing.Final = ast.parse(source_text, filename=source_name)
    global_bindings: typing.Final = collect_bindings(syntax_tree.body, {})
    module_classes: typing.Final = {
        one_statement_node.name: one_statement_node
        for one_statement_node in syntax_tree.body
        if isinstance(one_statement_node, ast.ClassDef)
    }
    all_classes: typing.Final = (
        one_source_node for one_source_node in ast.walk(syntax_tree) if isinstance(one_source_node, ast.ClassDef)
    )
    diagnostics_found: typing.Final = [*check_dispatch(syntax_tree), *check_type_dispatch(syntax_tree, module_classes)]
    diagnostics_found.extend(check_interface_usage(syntax_tree, module_classes, global_bindings=global_bindings))
    for one_class_definition in all_classes:
        diagnostics_found.extend(check_dataclass_factory(one_class_definition, global_bindings))
        for one_method_definition in one_class_definition.body:
            if not isinstance(one_method_definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            diagnostics_found.extend(
                check_method(
                    class_definition=one_class_definition,
                    method_definition=one_method_definition,
                    module_classes=module_classes,
                    global_bindings=global_bindings,
                )
            )
            diagnostics_found.extend(
                check_method_responsibility(
                    class_definition=one_class_definition,
                    method_definition=one_method_definition,
                    module_classes=module_classes,
                    global_bindings=global_bindings,
                )
            )
        diagnostics_found.extend(check_local_dependency(one_class_definition, module_classes))
    return diagnostics_found
