import sys
import textwrap
import typing

import pytest

from tests.test_commands import INPUT_ERROR_EXIT, run_checker

if typing.TYPE_CHECKING:
    import pathlib

REQUIRES_PYTHON_315: typing.Final = pytest.mark.skipif(
    sys.version_info < (3, 15), reason="Unpacking comprehensions require Python 3.15"
)


@pytest.mark.parametrize(
    ("method_body", "expected_findings"),
    [
        ("return sum(values)", 1),
        ('"self is only documentation"\n# self is only a comment\nreturn "self"', 1),
        ("return self.balance + sum(values)", 0),
        ("return consume_value(self)", 0),
        ("self.balance = sum(values)", 0),
        ("return lambda: self.balance", 0),
        ("return lambda self: self.balance", 1),
        ("def inner_scope(self):\n    return self.balance\nreturn inner_scope(values)", 1),
        ("def inner_scope():\n    return self.balance\nreturn inner_scope", 0),
        ("return [self.balance for item in values]", 0),
        ("return {self.balance for item in values}", 0),
        ("return {item: self.balance for item in values}", 0),
        ("return [self for self in values]", 1),
        ("return [self for self in self.values]", 0),
        ("return [self for item in values for self in item]", 1),
        ("return (self.balance for item in values)", 0),
        ("return super().compute_total(values)", 0),
        ("pass", 0),
        ("...", 0),
        ("raise NotImplementedError", 0),
        pytest.param("return [*self.items for item in values]", 0, marks=REQUIRES_PYTHON_315),
        pytest.param("return {*self.items for item in values}", 0, marks=REQUIRES_PYTHON_315),
        pytest.param("return {**self.mapping for item in values}", 0, marks=REQUIRES_PYTHON_315),
        pytest.param("return [*self for self in values]", 1, marks=REQUIRES_PYTHON_315),
        pytest.param("return {**self for self in values}", 1, marks=REQUIRES_PYTHON_315),
    ],
)
def test_check_receiver_use_in_body(tmp_path: pathlib.Path, method_body: str, expected_findings: int) -> None:
    source_path: typing.Final = tmp_path / "receiver_usage.py"
    source_path.write_text(
        "class CalculationService:\n    def compute_total(self, values):\n" + textwrap.indent(method_body, "        "),
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(source_path, checker_options=("--no-types",))

    assert completed_process.returncode != INPUT_ERROR_EXIT, completed_process.stdout + completed_process.stderr
    assert completed_process.stdout.count("PLS006 [SRP]") == expected_findings
    assert ("PLS006" in completed_process.stdout) == bool(expected_findings)


@pytest.mark.parametrize(
    ("source_text", "expected_code"),
    [
        ("class ExampleService:\n @staticmethod\n def compute_total(values): return sum(values)", "PLS005"),
        (
            (
                "from builtins import staticmethod as static_alias\n"
                "class ExampleService:\n"
                " @static_alias\n"
                " def compute_total(values): return sum(values)"
            ),
            "PLS005",
        ),
        (
            (
                "from typing import Protocol\n"
                "class ExampleService(Protocol):\n"
                " @staticmethod\n"
                " def compute_total(values): ..."
            ),
            "PLS005",
        ),
        ("class ExampleService:\n @classmethod\n def compute_total(cls, values): return sum(values)", "PLS006"),
        ("class ExampleService:\n @classmethod\n def compute_total(cls, values): return cls(values)", ""),
        ("class ExampleService:\n def compute_total(instance, /, values): return sum(values)", "PLS006"),
        ("class ExampleService:\n def compute_total(instance, /, values): return instance.balance", ""),
        ("class ExampleService:\n async def compute_total(self, values): return sum(values)", "PLS006"),
        (
            "class ExampleService:\n def compute_total(self, values: 'self' = 'self') -> 'self': return sum(values)",
            "PLS006",
        ),
        (
            (
                "from abc import abstractmethod\n"
                "class ExampleService:\n"
                " @abstractmethod\n"
                " def compute_total(self, values): return sum(values)"
            ),
            "",
        ),
        ("from typing import Protocol\nclass ExampleService(Protocol):\n def compute_total(self, values): ...", ""),
        ("class ExampleService:\n def __repr__(self): return 'example'", ""),
        (
            (
                "class ParentService:\n"
                " def compute_total(self, values): return self.balance\n"
                "class ChildService(ParentService):\n"
                " def compute_total(self, values): return sum(values)"
            ),
            "",
        ),
        (
            (
                "from typing import override\n"
                "class ExampleService(ExternalBase):\n"
                " @override\n"
                " def compute_total(self, values): return sum(values)"
            ),
            "",
        ),
        (
            (
                "class ExampleService:\n"
                " def compute_total(self, values):  # pylines-solid: ignore[PLS006] -- externally required callback\n"
                "  return sum(values)"
            ),
            "",
        ),
        (
            (
                "class ExampleService:\n"
                " @staticmethod\n"
                " def compute_total(values):  # pylines-solid: ignore[PLS005] -- external serializer API\n"
                "  return sum(values)"
            ),
            "",
        ),
    ],
)
def test_check_method_binding(tmp_path: pathlib.Path, source_text: str, expected_code: str) -> None:
    source_path: typing.Final = tmp_path / "method_binding.py"
    source_path.write_text(source_text, encoding="utf-8")

    completed_process: typing.Final = run_checker(source_path, checker_options=("--no-types",))

    assert completed_process.returncode == bool(expected_code), completed_process.stdout + completed_process.stderr
    assert (f"{expected_code} [SRP]" in completed_process.stdout) if expected_code else not completed_process.stdout
