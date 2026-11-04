import argparse
import collections.abc
import pathlib
import sys
import tokenize
import typing

from pylines_solid.analysis import check_source
from pylines_solid.comments import apply_suppressions
from pylines_solid.diagnostics import Diagnostic

SKIPPED_DIRECTORIES: typing.Final = frozenset(
    {".git", ".venv", "venv", "__pycache__", "build", "dist", ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache"},
)
EXIT_FINDINGS: typing.Final = 1
EXIT_INVALID: typing.Final = 2


def raise_walk_error(walk_error: OSError) -> typing.NoReturn:
    raise walk_error


def collect_sources(source_paths: list[str]) -> list[pathlib.Path]:
    collected_paths: typing.Final[set[pathlib.Path]] = set()
    for one_path_argument in source_paths:
        source_path = pathlib.Path(one_path_argument)
        if source_path.is_symlink():
            raise ValueError(f"Symlink input is not supported: {source_path}")
        if source_path.is_file():
            if source_path.suffix != ".py":
                raise ValueError(f"Expected a Python file: {source_path}")
            collected_paths.add(source_path.absolute())
        elif source_path.is_dir():
            for one_directory_path, one_directory_names, one_file_names in source_path.walk(on_error=raise_walk_error):
                one_directory_names[:] = sorted(set(one_directory_names) - SKIPPED_DIRECTORIES)
                collected_paths.update(
                    (one_directory_path / one_file_name).absolute()
                    for one_file_name in one_file_names
                    if one_file_name.endswith(".py") and not (one_directory_path / one_file_name).is_symlink()
                )
        else:
            raise ValueError(f"Path does not exist or is not a regular file: {source_path}")
    if not collected_paths:
        raise ValueError("No Python files found.")
    return sorted(collected_paths)


def check_source_file(source_path: pathlib.Path) -> list[Diagnostic]:
    if not source_path.is_file():
        return [
            Diagnostic(
                line_number=1,
                column_number=1,
                rule_code="PLS000",
                message_text=f"Not a regular file: {source_path}",
            ),
        ]
    try:
        with tokenize.open(source_path) as source_stream:
            source_text: typing.Final = source_stream.read()
        return apply_suppressions(source_text, check_source(source_text, str(source_path)))
    except (OSError, UnicodeError, SyntaxError, tokenize.TokenError) as caught_error:
        return [
            Diagnostic(
                line_number=(caught_error.lineno or 1) if isinstance(caught_error, SyntaxError) else 1,
                column_number=(caught_error.offset or 1) if isinstance(caught_error, SyntaxError) else 1,
                rule_code="PLS000",
                message_text=caught_error.msg if isinstance(caught_error, SyntaxError) else str(caught_error),
            ),
        ]


def run_command(command_arguments: collections.abc.Sequence[str] | None = None) -> int:
    argument_parser: typing.Final = argparse.ArgumentParser(description="Check concrete SOLID patterns from pylines.")
    argument_parser.add_argument("paths", nargs="*", default=["."], help="Python files or directories (default: .)")
    parsed_arguments: typing.Final = argument_parser.parse_args(command_arguments)
    try:
        source_paths: typing.Final = collect_sources(parsed_arguments.paths)
    except (OSError, ValueError) as caught_error:
        sys.stdout.write(f"<input>:1:1: PLS000 {caught_error}\n")
        return EXIT_INVALID
    exit_statuses: typing.Final = {0}
    for one_source_path in source_paths:
        for one_diagnostic in check_source_file(one_source_path):
            sys.stdout.write(
                f"{one_source_path}:{one_diagnostic.line_number}:{one_diagnostic.column_number}: "
                f"{one_diagnostic.rule_code} {one_diagnostic.message_text}\n",
            )
            exit_statuses.add(EXIT_INVALID if one_diagnostic.rule_code == "PLS000" else EXIT_FINDINGS)
    return max(exit_statuses)
