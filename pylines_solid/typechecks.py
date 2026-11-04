import importlib.util
import json
import pathlib
import subprocess
import sys
import typing

from pylines_solid.diagnostics import Diagnostic

TYPE_CHECK_TIMEOUT: typing.Final = 120
OVERRIDE_CODES: typing.Final = frozenset({"override", "mutable-override"})


def parse_type_diagnostic(message_record: object) -> tuple[pathlib.Path, Diagnostic]:
    if not isinstance(message_record, dict):
        raise TypeError("mypy returned an invalid diagnostic.")
    source_name: typing.Final = message_record.get("file")
    line_number: typing.Final = message_record.get("line")
    column_number: typing.Final = message_record.get("column")
    message_text: typing.Final = message_record.get("message")
    error_code: typing.Final = message_record.get("code")
    if not (
        isinstance(source_name, str)
        and isinstance(line_number, int)
        and isinstance(column_number, int)
        and isinstance(message_text, str)
        and isinstance(error_code, str)
    ):
        raise TypeError("mypy returned an incomplete diagnostic.")
    message_hint: typing.Final = message_record.get("hint")
    message_suffix: typing.Final = " | " + message_hint.replace("\n", " | ") if isinstance(message_hint, str) else ""
    is_override: typing.Final = error_code in OVERRIDE_CODES
    return pathlib.Path(source_name).resolve(), Diagnostic(
        line_number=max(1, line_number),
        column_number=max(1, column_number + 1),
        rule_code="PLS007" if is_override else "MYPY",
        message_text=(f"[LSP] {message_text}" if is_override else f"[{error_code}] {message_text}") + message_suffix,
    )


def check_types(source_paths: list[pathlib.Path]) -> dict[pathlib.Path, list[Diagnostic]]:
    if importlib.util.find_spec("mypy") is None:
        raise ValueError("mypy is missing; reinstall pylines-solid with its dependencies in the project environment.")
    if any(not one_source_path.is_file() for one_source_path in source_paths):
        raise ValueError("Type checking requires regular Python files.")
    completed_process: typing.Final = subprocess.run(  # noqa: S603 -- fixed interpreter and module; paths are separate arguments
        [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--output",
            "json",
            "--no-error-summary",
            "--enable-error-code",
            "override",
            "--enable-error-code",
            "mutable-override",
            *(str(one_source_path) for one_source_path in source_paths),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=TYPE_CHECK_TIMEOUT,
    )
    if completed_process.returncode not in {0, 1}:
        raise ValueError(f"mypy failed: {completed_process.stderr.strip() or completed_process.stdout.strip()}")
    diagnostics_by_path: typing.Final[dict[pathlib.Path, list[Diagnostic]]] = {}
    for one_output_line in completed_process.stdout.splitlines():
        source_path, type_diagnostic = parse_type_diagnostic(json.loads(one_output_line))
        diagnostics_by_path.setdefault(source_path, []).append(type_diagnostic)
    if completed_process.returncode and not diagnostics_by_path:
        raise ValueError("mypy failed without returning diagnostics.")
    return diagnostics_by_path
