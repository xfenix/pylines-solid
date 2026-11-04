import os
import pathlib
import re
import subprocess
import sys
import textwrap
import typing

import pytest

PROCESS_TIMEOUT: typing.Final = 10
FIFO_TIMEOUT_SECONDS: typing.Final = 2
INPUT_ERROR_EXIT: typing.Final = 2


def run_checker(
    *source_paths: pathlib.Path,
    working_directory: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pylines_solid", *(str(one_source_path) for one_source_path in source_paths)],
        cwd=working_directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=PROCESS_TIMEOUT,
    )


@pytest.mark.parametrize(
    ("source_text", "expected_codes"),
    [
        pytest.param(
            """
            class ParentBird:
                def perform_flight(self):
                    return "flying"

            class PenguinBird(ParentBird):
                def perform_flight(self):
                    "Cannot fly."
                    raise NotImplementedError("Penguins cannot fly")
            """,
            ("PLS001",),
            id="inherited-behavior-refused",
        ),
        pytest.param(
            """
            class ParentBird:
                def perform_flight(self):
                    ...

            class PenguinBird(ParentBird):
                def perform_flight(self):
                    raise NotImplementedError
            """,
            ("PLS001",),
            id="pylines-ellipsis-is-not-abstract",
        ),
        pytest.param(
            """
            import typing

            class SmartDevice(typing.Protocol):
                def control_temperature(self):
                    ...

            class SmartLight:
                def control_temperature(self):
                    raise NotImplementedError("A light cannot heat")
            """,
            ("PLS002",),
            id="structural-interface-refused",
        ),
        pytest.param(
            """
            from abc import abstractmethod

            class DeviceContract:
                @abstractmethod
                def control_temperature(self):
                    raise NotImplementedError

            class SmartLight(DeviceContract):
                def control_temperature(self):
                    raise NotImplementedError
            """,
            ("PLS002",),
            id="abstract-parent-concrete-refusal",
        ),
        pytest.param(
            """
            import abc

            class ReaderContract(abc.ABC):
                from abc import abstractmethod

                @abstractmethod
                def fetch_payload(self):
                    raise NotImplementedError
            """,
            (),
            id="class-local-abstract-decorator",
        ),
        pytest.param(
            """
            import abc

            class ReaderContract(abc.ABC):
                from abc import abstractmethod

                @abstractmethod
                def fetch_payload(self):
                    raise NotImplementedError

            class RefusingReader(ReaderContract):
                def fetch_payload(self):
                    raise NotImplementedError
            """,
            ("PLS002",),
            id="inherited-class-local-abstract-decorator",
        ),
        pytest.param(
            """
            import abc
            from typing import Protocol as DeviceProtocol

            class AbstractDevice(abc.ABC):
                @abc.abstractmethod
                def control_temperature(self):
                    raise NotImplementedError

            class DeviceContract(DeviceProtocol):
                def control_temperature(self):
                    raise NotImplementedError
            """,
            (),
            id="abstract-and-protocol-declarations",
        ),
        pytest.param(
            """
            class ParentBird:
                def perform_flight(self):
                    return "flying"

            class FlyingBird(ParentBird):
                def perform_flight(self):
                    return super().perform_flight()

            class SmartLight:
                def illuminate_room(self):
                    return "light"
            """,
            (),
            id="implemented-capability-and-small-interface",
        ),
        pytest.param(
            """
            class SmartDevice:
                async def control_temperature(self):
                    raise NotImplementedError
            """,
            ("PLS002",),
            id="async-refusal",
        ),
        pytest.param(
            """
            class SmartDevice:
                def control_temperature(self, requested_temperature):
                    if requested_temperature < 0:
                        raise NotImplementedError
                    return requested_temperature
            """,
            (),
            id="conditional-failure-is-outside-narrow-rule",
        ),
    ],
)
def test_check_declared_capabilities(
    tmp_path: pathlib.Path,
    source_text: str,
    expected_codes: tuple[str, ...],
) -> None:
    source_path: typing.Final = tmp_path / "capabilities.py"
    source_path.write_text(textwrap.dedent(source_text), encoding="utf-8")

    completed_process: typing.Final = run_checker(source_path)

    assert completed_process.returncode == int(bool(expected_codes)), completed_process.stderr
    assert tuple(re.findall(r": (PLS\d{3}) ", completed_process.stdout)) == expected_codes


@pytest.mark.parametrize(
    ("import_statement", "constructor_expression"),
    [
        ("import httpx", "httpx.Client()"),
        ("import httpx as transport_module", "transport_module.AsyncClient()"),
        ("from httpx import Client as HttpConnection", "HttpConnection()"),
        ("import aiohttp", "aiohttp.ClientSession()"),
        ("import redis.asyncio", "redis.asyncio.Redis()"),
        ("from psycopg import connect as open_database", "open_database()"),
        ("from sqlalchemy.ext.asyncio import create_async_engine", "create_async_engine()"),
    ],
)
def test_report_infrastructure_construction(
    tmp_path: pathlib.Path,
    import_statement: str,
    constructor_expression: str,
) -> None:
    source_path: typing.Final = tmp_path / "connection_owner.py"
    source_path.write_text(
        f"{import_statement}\nclass FetchService:\n    async def fetch_remote(self):\n"
        f"        return {constructor_expression}\n",
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(source_path)

    assert completed_process.returncode == 1, completed_process.stderr
    assert re.fullmatch(rf"{re.escape(str(source_path))}:4:\d+: PLS003 .+\n", completed_process.stdout)


def test_report_client_despite_default_lambda_scope(tmp_path: pathlib.Path) -> None:
    source_path: typing.Final = tmp_path / "default_scope.py"
    source_path.write_text(
        "import httpx\nclass FetchService:\n"
        "    def fetch_remote(self, callback=lambda httpx: httpx):\n"
        "        return httpx.Client()\n",
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(source_path)

    assert completed_process.returncode == 1, completed_process.stderr
    assert "PLS003" in completed_process.stdout


@pytest.mark.parametrize(
    "source_text",
    [
        pytest.param(
            """
            import httpx

            def build_connection():
                return httpx.Client()

            class FetchService:
                def __init__(self, http_connection: httpx.Client):
                    self.http_connection = http_connection

                def fetch_remote(self):
                    return self.http_connection.get("https://example.invalid")
            """,
            id="factory-and-injected-client",
        ),
        pytest.param(
            """
            import httpx

            class FetchService:
                def fetch_remote(self, httpx):
                    return httpx.Client()
            """,
            id="parameter-shadows-import",
        ),
        pytest.param(
            """
            from httpx import Client as HttpConnection

            class FetchService:
                def fetch_remote(self, replacement_factory):
                    HttpConnection = replacement_factory
                    return HttpConnection()
            """,
            id="local-binding-shadows-import",
        ),
        pytest.param(
            """
            import httpx
            httpx = replacement_module

            class FetchService:
                def fetch_remote(self):
                    return httpx.Client()
            """,
            id="module-binding-shadows-import",
        ),
        pytest.param(
            """
            import httpx

            class FetchService:
                def fetch_remote(self, replacement_module):
                    match replacement_module:
                        case {"transport": httpx}:
                            return httpx.Client()
                    return None
            """,
            id="match-binding-shadows-import",
        ),
        pytest.param(
            """
            import httpx
            from external_adapter import *

            class FetchService:
                def fetch_remote(self):
                    return httpx.Client()
            """,
            id="star-import-makes-module-binding-uncertain",
        ),
        pytest.param(
            """
            import httpx

            class FetchService:
                def fetch_remote(self):
                    def build_connection():
                        return httpx.Client()
                    return build_connection
            """,
            id="nested-factory-is-not-a-method",
        ),
    ],
)
def test_accept_dependency_injection_and_shadowed_imports(tmp_path: pathlib.Path, source_text: str) -> None:
    source_path: typing.Final = tmp_path / "accepted_connections.py"
    source_path.write_text(textwrap.dedent(source_text), encoding="utf-8")

    completed_process: typing.Final = run_checker(source_path)

    assert (completed_process.returncode, completed_process.stdout) == (0, "")


def test_report_method_local_import(tmp_path: pathlib.Path) -> None:
    source_path: typing.Final = tmp_path / "local_import.py"
    source_path.write_text(
        "class FetchService:\n    def fetch_remote(self):\n"
        "        from httpx import AsyncClient as HttpConnection\n        return HttpConnection()\n",
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(source_path)

    assert completed_process.returncode == 1
    assert ": PLS003 " in completed_process.stdout


@pytest.mark.parametrize(
    ("source_expression", "expected_exit", "expected_code"),
    [
        (
            "httpx.Client()  # pylines-solid: ignore[PLS003] -- adapter owns connection lifetime",
            0,
            "",
        ),
        ('httpx.Client("# pylines-solid: ignore[PLS003] -- this is a string")', 1, "PLS003"),
        ("httpx.Client()  # pylines-solid: ignore[PLS003]", INPUT_ERROR_EXIT, "PLS000"),
        ("httpx.Client()  # pylines-solid: ignore[PLS999] -- unknown rule", INPUT_ERROR_EXIT, "PLS000"),
        ("None  # pylines-solid: ignore[PLS003] -- obsolete exemption", INPUT_ERROR_EXIT, "PLS000"),
    ],
)
def test_require_real_targeted_suppressions(
    tmp_path: pathlib.Path,
    source_expression: str,
    expected_exit: int,
    expected_code: str,
) -> None:
    source_path: typing.Final = tmp_path / "suppressed_connection.py"
    source_path.write_text(
        f"import httpx\nclass FetchService:\n    def fetch_remote(self):\n        return {source_expression}\n",
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(source_path)

    assert completed_process.returncode == expected_exit, completed_process.stderr
    assert expected_code in completed_process.stdout


@pytest.mark.parametrize("source_bytes", [b"class BrokenClass(\n", b"\xff\xfe"])
def test_reject_unreadable_python(tmp_path: pathlib.Path, source_bytes: bytes) -> None:
    source_path: typing.Final = tmp_path / "invalid_source.py"
    source_path.write_bytes(source_bytes)

    completed_process: typing.Final = run_checker(source_path)

    assert completed_process.returncode == INPUT_ERROR_EXIT
    assert ": PLS000 " in completed_process.stdout


@pytest.mark.parametrize("target_name", ["missing_source.py", "."])
def test_reject_missing_or_empty_input(tmp_path: pathlib.Path, target_name: str) -> None:
    completed_process: typing.Final = run_checker(tmp_path / target_name)

    assert completed_process.returncode == INPUT_ERROR_EXIT
    assert ": PLS000 " in completed_process.stdout


def test_read_declared_encoding_without_executing_source(tmp_path: pathlib.Path) -> None:
    marker_path: typing.Final = tmp_path / "execution_marker"
    source_path: typing.Final = tmp_path / "encoded_source.py"
    source_path.write_bytes(
        f"# coding: latin-1\nimport pathlib\npathlib.Path({str(marker_path)!r}).write_text('café')\n".encode("latin-1")
    )

    completed_process: typing.Final = run_checker(source_path)

    assert completed_process.returncode == 0
    assert not marker_path.exists()


def test_scan_sorted_unique_files_without_following_symlink_directories(tmp_path: pathlib.Path) -> None:
    project_path: typing.Final = tmp_path / "project_sources"
    project_path.mkdir()
    ignored_path: typing.Final = project_path / ".venv"
    ignored_path.mkdir()
    outside_path: typing.Final = tmp_path / "outside_sources"
    outside_path.mkdir()
    refusal_source: typing.Final = (
        "class SmartDevice:\n    def control_temperature(self):\n        raise NotImplementedError\n"
    )
    (ignored_path / "ignored_source.py").write_text(refusal_source, encoding="utf-8")
    (outside_path / "outside_source.py").write_text(refusal_source, encoding="utf-8")
    (project_path / "external_sources").symlink_to(outside_path, target_is_directory=True)
    source_paths: typing.Final = (project_path / "alpha_source.py", project_path / "zulu_source.py")
    for one_source_path in source_paths:
        one_source_path.write_text(refusal_source, encoding="utf-8")

    completed_process: typing.Final = run_checker(project_path, *source_paths)

    assert completed_process.returncode == 1
    assert tuple(
        one_diagnostic.split(":", maxsplit=1)[0] for one_diagnostic in completed_process.stdout.splitlines()
    ) == tuple(str(one_source_path) for one_source_path in source_paths)


def test_default_to_current_directory(tmp_path: pathlib.Path) -> None:
    (tmp_path / "clean_source.py").write_text("package_version = 'example'\n", encoding="utf-8")

    completed_process: typing.Final = run_checker(working_directory=tmp_path)

    assert (completed_process.returncode, completed_process.stdout) == (0, "")


def test_report_client_created_in_protocol_default_method(tmp_path: pathlib.Path) -> None:
    source_path: typing.Final = tmp_path / "protocol_client.py"
    source_path.write_text(
        "import httpx\nfrom typing import Protocol\nclass ReaderContract(Protocol):\n"
        "    def fetch_payload(self):\n        return httpx.Client()\n",
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(source_path)

    assert completed_process.returncode == 1
    assert ": PLS003 " in completed_process.stdout


def test_reject_named_pipe_during_directory_scan(tmp_path: pathlib.Path) -> None:
    os.mkfifo(tmp_path / "waiting_source.py")
    (tmp_path / "regular_source.py").write_text("package_version = 'example'\n", encoding="utf-8")

    completed_process: typing.Final = subprocess.run(
        [sys.executable, "-m", "pylines_solid", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=FIFO_TIMEOUT_SECONDS,
    )

    assert completed_process.returncode == INPUT_ERROR_EXIT
    assert ": PLS000 " in completed_process.stdout
