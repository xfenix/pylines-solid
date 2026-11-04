import os
import subprocess
import sys
import typing

import pytest

from tests.test_commands import INPUT_ERROR_EXIT, run_checker

if typing.TYPE_CHECKING:
    import pathlib


@pytest.mark.parametrize(
    ("parent_arguments", "child_arguments", "return_types", "expected_violation"),
    [
        ("input_value: GeneralValue", "input_value: SpecialValue", ("GeneralValue", "GeneralValue"), True),
        ("input_value: SpecialValue", "input_value: GeneralValue", ("GeneralValue", "GeneralValue"), False),
        ("input_value: GeneralValue", "input_value: GeneralValue", ("SpecialValue", "GeneralValue"), True),
        ("input_value: GeneralValue", "input_value: GeneralValue", ("GeneralValue", "SpecialValue"), False),
        (
            "input_value: GeneralValue, token_value: str = ''",
            "input_value: GeneralValue, token_value: str",
            ("GeneralValue", "GeneralValue"),
            True,
        ),
        (
            "input_value: GeneralValue",
            "input_value: GeneralValue, token_value: str",
            ("GeneralValue", "GeneralValue"),
            True,
        ),
        (
            "input_value: GeneralValue",
            "input_value: GeneralValue, *, token_value: str = ''",
            ("GeneralValue", "GeneralValue"),
            False,
        ),
        ("*, input_value: GeneralValue", "*, renamed_value: GeneralValue", ("GeneralValue", "GeneralValue"), True),
    ],
)
def test_check_inherited_type_contracts(
    tmp_path: pathlib.Path,
    parent_arguments: str,
    child_arguments: str,
    return_types: tuple[str, str],
    *,
    expected_violation: bool,
) -> None:
    parent_return, child_return = return_types
    (tmp_path / "contracts.py").write_text(
        "class GeneralValue: pass\n"
        "class SpecialValue(GeneralValue): pass\n"
        "class ParentService:\n"
        f"    def handle_value(self, {parent_arguments}) -> {parent_return}:\n"
        f"        self.last_value = input_value\n        return {parent_return}()\n",
        encoding="utf-8",
    )
    (tmp_path / "implementation.py").write_text(
        "from typing import override\nfrom contracts import GeneralValue, SpecialValue, ParentService\n"
        "class ChildService(ParentService):\n    @override\n"
        f"    def handle_value(self, {child_arguments}) -> {child_return}:\n        return {child_return}()\n",
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(tmp_path, working_directory=tmp_path, checker_options=("--types",))

    assert completed_process.returncode == expected_violation, completed_process.stdout + completed_process.stderr
    assert ("PLS007 [LSP]" in completed_process.stdout) == expected_violation
    assert "MYPY" not in completed_process.stdout


@pytest.mark.parametrize("suppress_violation", [False, True])
def test_check_generic_specialization(tmp_path: pathlib.Path, *, suppress_violation: bool) -> None:
    source_path: typing.Final = tmp_path / "generic_contract.py"
    suppression_text: typing.Final = (
        "  # pylines-solid: ignore[PLS007] -- compatibility boundary under migration" if suppress_violation else ""
    )
    source_path.write_text(
        "from typing import override\n"
        "class GeneralValue: pass\n"
        "class SpecialValue(GeneralValue): pass\n"
        "class ParentService[ValueType]:\n"
        "    def handle_value(self, input_value: ValueType) -> ValueType:\n"
        "        self.last_value = input_value\n        return input_value\n"
        "class ChildService(ParentService[GeneralValue]):\n    @override\n"
        f"    def handle_value(self, input_value: SpecialValue) -> GeneralValue:{suppression_text}\n"
        "        return input_value\n",
        encoding="utf-8",
    )

    completed_process: typing.Final = run_checker(source_path, working_directory=tmp_path, checker_options=("--types",))

    assert completed_process.returncode == (not suppress_violation), completed_process.stdout + completed_process.stderr
    assert ("PLS007 [LSP]" in completed_process.stdout) == (not suppress_violation)


@pytest.mark.parametrize(
    ("source_text", "expected_marker"),
    [
        (
            (
                "class GeneralValue: pass\n"
                "class SpecialValue(GeneralValue): pass\n"
                "class ParentService:\n current_value: GeneralValue\n"
                "class ChildService(ParentService):\n current_value: SpecialValue"
            ),
            "PLS007 [LSP]",
        ),
        ("def process_value(input_value):\n return input_value", "MYPY [no-untyped-def]"),
        ("import missing_contract_package_98452", "MYPY [import-not-found]"),
    ],
)
def test_report_type_contract_gaps(tmp_path: pathlib.Path, source_text: str, expected_marker: str) -> None:
    source_path: typing.Final = tmp_path / "typing_gap.py"
    source_path.write_text(source_text, encoding="utf-8")

    completed_process: typing.Final = run_checker(source_path, working_directory=tmp_path, checker_options=("--types",))

    assert completed_process.returncode == 1, completed_process.stdout + completed_process.stderr
    assert expected_marker in completed_process.stdout


def test_require_type_engine_for_types_mode(tmp_path: pathlib.Path) -> None:
    source_path: typing.Final = tmp_path / "valid_source.py"
    source_path.write_text("value_count = 1\n", encoding="utf-8")

    completed_process: typing.Final = subprocess.run(
        [sys.executable, "-S", "-m", "pylines_solid", "--types", str(source_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed_process.returncode == INPUT_ERROR_EXIT
    assert "PLS000" in completed_process.stdout
    assert "types extra" in completed_process.stdout


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Named pipes are unavailable on this platform")
def test_reject_named_pipe_before_type_analysis(tmp_path: pathlib.Path) -> None:
    os.mkfifo(tmp_path / "waiting_source.py")

    completed_process: typing.Final = run_checker(tmp_path, working_directory=tmp_path, checker_options=("--types",))

    assert completed_process.returncode == INPUT_ERROR_EXIT
    assert "regular Python files" in completed_process.stdout


def test_report_type_engine_configuration_failure(tmp_path: pathlib.Path) -> None:
    (tmp_path / "mypy.ini").write_text("[mypy]\nplugins = missing_project_plugin_98452\n", encoding="utf-8")
    source_path: typing.Final = tmp_path / "valid_source.py"
    source_path.write_text("value_count = 1\n", encoding="utf-8")

    completed_process: typing.Final = run_checker(source_path, working_directory=tmp_path, checker_options=("--types",))

    assert completed_process.returncode == INPUT_ERROR_EXIT
    assert "PLS000 mypy failed" in completed_process.stdout
