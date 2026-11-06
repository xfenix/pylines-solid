"""Regressions from the pylines SOLID coverage audit."""

import textwrap
import typing

import pytest

from tests.test_commands import run_checker

if typing.TYPE_CHECKING:
    import pathlib


@pytest.mark.parametrize(
    ("source_text", "expected_code"),
    [
        pytest.param(
            """
            def calculate_value(input_value):
                class Calculator:
                    @staticmethod
                    def double_value(input_value):
                        return input_value * 2
                return Calculator.double_value(input_value)
            """,
            "PLS005 [SRP]",
            id="nested-static-method",
        ),
        pytest.param(
            """
            class ParentShape: pass
            class CircleShape(ParentShape):
                def draw_shape(self): return "circle"
            class RectangleShape(ParentShape):
                def draw_shape(self): return "rectangle"
            def draw_some_shape(one_shape: ParentShape):
                if isinstance(one_shape, CircleShape) or isinstance(one_shape, RectangleShape):
                    return one_shape.draw_shape()
            """,
            "PLS008 [OCP/LSP]",
            id="pylines-type-dispatch",
        ),
        pytest.param(
            """
            class MailNotifier:
                def send_message(self, message): return f"{self}: {message}"
            class OrderService:
                def __init__(self): self.notifier = MailNotifier()
                def complete_order(self, order_number):
                    return self.notifier.send_message(str(order_number))
            """,
            "PLS009 [DIP]",
            id="service-owns-local-collaborator",
        ),
        pytest.param(
            """
            from typing import Protocol
            class SmartDevice(Protocol):
                def turn_on(self) -> None: ...
                def turn_off(self) -> None: ...
                def play_music(self, track: str) -> None: ...
            def activate_device(device: SmartDevice) -> None:
                device.turn_on()
            """,
            "PLS011 [ISP]",
            id="client-requires-unused-protocol-capabilities",
        ),
        pytest.param(
            """
            class BalanceReader:
                def read_balance(self, account_number: int) -> int:
                    return account_number + self.balance
            class PositiveBalanceReader(BalanceReader):
                def read_balance(self, account_number: int) -> int:
                    if account_number <= 0:
                        raise ValueError("positive required")
                    return account_number + self.balance
            """,
            "PLS010 [LSP]",
            id="override-adds-guarded-rejection",
        ),
    ],
)
def test_report_new_solid_signals(tmp_path: pathlib.Path, source_text: str, expected_code: str) -> None:
    source_path: typing.Final = tmp_path / "solid_regression.py"
    source_path.write_text(textwrap.dedent(source_text).lstrip(), encoding="utf-8")

    completed_process: typing.Final = run_checker(source_path, checker_options=("--no-types",))

    assert completed_process.returncode == 1, completed_process.stdout + completed_process.stderr
    assert expected_code in completed_process.stdout


@pytest.mark.parametrize(
    "source_text",
    [
        pytest.param(
            """
            def read_value(input_value):
                if isinstance(input_value, str) or isinstance(input_value, bytes):
                    return input_value
            """,
            id="unrelated-builtins-validation",
        ),
        pytest.param(
            """
            class ParentShape:
                def draw_shape(self): return str(self)
            class CircleShape(ParentShape):
                def draw_shape(self): return str(self)
            class RectangleShape(ParentShape):
                def draw_shape(self): return str(self)
            def draw_some_shape(one_shape: ParentShape):
                if isinstance(one_shape, CircleShape) or isinstance(one_shape, RectangleShape):
                    return one_shape.draw_shape()
            """,
            id="base-declares-shared-capability",
        ),
        pytest.param(
            """
            class MailNotifier:
                def send_message(self, message): return f"{self}: {message}"
            class OrderService:
                def __init__(self, notifier: MailNotifier): self.notifier = notifier
                def complete_order(self, order_number):
                    return self.notifier.send_message(str(order_number))
            """,
            id="injected-collaborator",
        ),
        pytest.param(
            """
            from typing import Protocol
            class SmartDevice(Protocol):
                def turn_on(self) -> None: ...
                def turn_off(self) -> None: ...
            def activate_device(device: SmartDevice) -> None:
                device.turn_on()
                device.turn_off()
            """,
            id="client-uses-entire-protocol",
        ),
        pytest.param(
            """
            from typing import Protocol
            class SmartDevice(Protocol):
                def turn_on(self) -> None: ...
                def turn_off(self) -> None: ...
            def forward_device(device: SmartDevice) -> None:
                consume_device(device)
            """,
            id="client-forwards-protocol",
        ),
        pytest.param(
            """
            class BalanceReader:
                def read_balance(self, account_number: int) -> int:
                    if account_number <= 0:
                        raise ValueError("positive required")
                    return account_number + self.balance
            class PositiveBalanceReader(BalanceReader):
                def read_balance(self, account_number: int) -> int:
                    if account_number <= 0:
                        raise ValueError("positive required")
                    return account_number + self.balance
            """,
            id="inherited-precondition-unchanged",
        ),
    ],
)
def test_accept_unchanged_contracts(tmp_path: pathlib.Path, source_text: str) -> None:
    source_path: typing.Final = tmp_path / "accepted_contract.py"
    source_path.write_text(textwrap.dedent(source_text).lstrip(), encoding="utf-8")

    completed_process: typing.Final = run_checker(source_path, checker_options=("--no-types",))

    assert (completed_process.returncode, completed_process.stdout) == (0, "")
