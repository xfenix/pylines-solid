import textwrap
import typing

import pytest

from tests.test_commands import run_checker

if typing.TYPE_CHECKING:
    import pathlib


@pytest.mark.parametrize(
    ("source_text", "expected_findings"),
    [
        pytest.param(
            """
            def run_command(command_name):
                if command_name == "list-pods": return list_pods()
                elif command_name == "scale": return scale_pods()
                elif command_name == "--help":
                    print("Available commands: list-pods, scale")
                    return
                raise SystemExit(command_name)
            """,
            1,
            id="pylines-command-dispatch",
        ),
        pytest.param(
            """
            async def run_command(command_name):
                if command_name == "list": return await list_pods()
                elif command_name == "scale": return await scale_pods()
                elif command_name == "delete": return await delete_pods()
                elif command_name == "create": return await create_pods()
            """,
            1,
            id="one-finding-per-async-chain",
        ),
        pytest.param(
            """
            class CommandRunner:
                def run_command(self, command_name):
                    match command_name:
                        case "list": return self.list_pods()
                        case "scale": return self.scale_pods()
                        case "delete": return self.delete_pods()
                        case _: raise ValueError(command_name)
            """,
            1,
            id="match-dispatch-in-method",
        ),
        pytest.param(
            """
            def run_command(command):
                if "list" == command.name: list_pods()
                elif "scale" == command.name: scale_pods()
                elif "delete" == command.name: delete_pods()
            """,
            1,
            id="reversed-comparison-and-attribute-selector",
        ),
        pytest.param(
            """
            def run_command(command_name):
                if command_name == "list": return list_pods()
                elif command_name == "scale": return scale_pods()
            """,
            0,
            id="two-routes-are-below-threshold",
        ),
        pytest.param(
            """
            def run_command(command_name):
                if command_name == "list": return execute_command("list")
                elif command_name == "scale": return execute_command("scale")
                elif command_name == "delete": return execute_command("delete")
            """,
            0,
            id="same-handler-is-not-handler-dispatch",
        ),
        pytest.param(
            """
            def run_command(command_name):
                if command_name == "list": return list_pods()
                elif command_name == "list": return scale_pods()
                elif command_name == "delete": return delete_pods()
            """,
            0,
            id="duplicate-selector-values",
        ),
        pytest.param(
            """
            def run_command(command_name, other_name):
                if command_name == "list": return list_pods()
                elif other_name == "scale": return scale_pods()
                elif command_name == "delete": return delete_pods()
            """,
            0,
            id="different-selectors",
        ),
        pytest.param(
            """
            def classify_volume(volume_value):
                if volume_value < 10: return describe_small()
                elif volume_value < 100: return describe_medium()
                elif volume_value < 1000: return describe_large()
            """,
            0,
            id="range-checks-are-not-dispatch",
        ),
        pytest.param(
            """
            def run_command(command_name, permission):
                if command_name == "list": return list_pods()
                elif command_name == "scale" and permission: return scale_pods()
                elif command_name == "delete": return delete_pods()
            """,
            0,
            id="compound-conditions",
        ),
        pytest.param(
            """
            def run_command(command_name):
                match command_name:
                    case "list": return list_pods()
                    case "scale" if permitted(): return scale_pods()
                    case "delete": return delete_pods()
            """,
            0,
            id="guarded-match",
        ),
        pytest.param(
            """
            def run_command(command_name):
                match command_name:
                    case "list" | "show": return list_pods()
                    case "scale": return scale_pods()
                    case "delete": return delete_pods()
            """,
            0,
            id="compound-match-patterns",
        ),
        pytest.param(
            """
            def run_command(command_name):
                if command_name == "list":
                    audit_request()
                    return list_pods()
                elif command_name == "scale": return scale_pods()
                elif command_name == "delete": return delete_pods()
            """,
            0,
            id="multi-step-branch",
        ),
        pytest.param(
            """
            def run_command():
                if read_command().name == "list": return list_pods()
                elif read_command().name == "scale": return scale_pods()
                elif read_command().name == "delete": return delete_pods()
            """,
            0,
            id="selector-is-evaluated-dynamically",
        ),
        pytest.param(
            """
            def run_command(command_name, available_commands):
                if command_name == "--help":
                    print(", ".join(available_commands))
                    return
                if command_handler := available_commands.get(command_name):
                    return command_handler()
                raise SystemExit(command_name)
            """,
            0,
            id="pylines-handler-registry",
        ),
        pytest.param(
            """
            def run_command(command_name):
                if command_name == "list":  # pylines-solid: ignore[PLS004] -- fixed wire protocol
                    return list_pods()
                elif command_name == "scale": return scale_pods()
                elif command_name == "delete": return delete_pods()
            """,
            0,
            id="reasoned-exception-on-chain-head",
        ),
    ],
)
def test_check_literal_dispatch(tmp_path: pathlib.Path, source_text: str, expected_findings: int) -> None:
    source_path: typing.Final = tmp_path / "command_dispatch.py"
    source_path.write_text(textwrap.dedent(source_text).lstrip(), encoding="utf-8")

    completed_process: typing.Final = run_checker(source_path, checker_options=("--no-types",))

    assert completed_process.returncode == bool(expected_findings), completed_process.stdout + completed_process.stderr
    assert completed_process.stdout.count("PLS004 [OCP]") == expected_findings
    assert len(completed_process.stdout.splitlines()) == expected_findings


@pytest.mark.parametrize("inject_connections", [False, True])
def test_separate_infrastructure_setup_from_user_behavior(tmp_path: pathlib.Path, *, inject_connections: bool) -> None:
    source_path: typing.Final = tmp_path / "user_service.py"
    setup_statements: typing.Final = (
        "database_connection = self.database_connection\nkafka_connection = self.kafka_connection"
        if inject_connections
        else "database_connection = await asyncpg.connect()\nkafka_connection = aiokafka.AIOKafkaProducer()"
    )
    source_path.write_text(
        "import asyncpg\nimport aiokafka\nclass UserService:\n    async def create_user(self, user_record):\n"
        + textwrap.indent(setup_statements, "        ")
        + '\n        await database_connection.execute("INSERT INTO users ...")\n'
        + '        await kafka_connection.send_and_wait("users", user_record)\n',
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(source_path, checker_options=("--no-types",))

    assert completed_process.returncode == (0 if inject_connections else 1), completed_process.stderr
    assert completed_process.stdout.count("PLS003 [SRP/DIP]") == (0 if inject_connections else 2)
