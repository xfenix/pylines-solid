# pylines-solid

[![CI](https://github.com/xfenix/pylines-solid/actions/workflows/check.yml/badge.svg?branch=main)](https://github.com/xfenix/pylines-solid/actions/workflows/check.yml)
[![Coverage at v0.5.0: 94%](https://img.shields.io/badge/coverage%20v0.5.0-94%25-brightgreen)](https://github.com/xfenix/pylines-solid/actions/runs/42139251976)

`pylines-solid` checks specific Python [SOLID patterns in pylines](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md) and two team rules about method ownership. It uses AST analysis and mypy. It does not use AI. Every finding names the principle and the change to consider.

## Quickstart

Use Python 3.14 or 3.15. Run the checker in your project environment so mypy can see your dependencies:

```sh
uv run --with 'pylines-solid @ git+https://github.com/xfenix/pylines-solid.git' pylines-solid .
```

AST and type checks run by default. Exit code `0` means no findings; `1` means findings; `2` means the check could not finish. Use `--no-types` only when you need AST checks without mypy. Pin a Git commit in CI. The package is not on PyPI.

## Rules

The examples show the pattern each rule checks. A finding is a review signal, not proof that a design is wrong.

### PLS001 — Keep inherited behavior [LSP]

A child method must not replace a working parent method with `NotImplementedError`.

#### ✅ Compliant

```python
class FlyingBird:
    def start_flight(self) -> str:
        return str(self)


class PenguinBird:
    def swim_underwater(self) -> str:
        return str(self)
```

#### ❌ Violation

```python
class ParentBird:
    def start_flight(self) -> str:
        return str(self)


class PenguinBird(ParentBird):
    def start_flight(self) -> str:
        raise NotImplementedError
```

### PLS002 — Remove unsupported capabilities [ISP]

A concrete method must not always reject a capability with `NotImplementedError`. Split the interface or make the method abstract.

#### ✅ Compliant

```python
class PrintableDevice:
    def print_document(self) -> str:
        return str(self)
```

#### ❌ Violation

```python
class PrintableDevice:
    def print_document(self) -> str:
        return str(self)

    def scan_document(self) -> str:
        raise NotImplementedError
```

### PLS003 — Inject infrastructure clients [SRP/DIP]

A service method must not create its own HTTP, database, Redis, or Kafka client. Pass the client into the service.

#### ✅ Compliant

```python
import httpx


class BalanceReader:
    def __init__(self, connection: httpx.Client) -> None:
        self.connection = connection

    def fetch_balance(self) -> httpx.Response:
        return self.connection.get("https://example.com/balance")
```

#### ❌ Violation

```python
import httpx


class BalanceReader:
    def fetch_balance(self) -> httpx.Response:
        connection = httpx.Client()
        return connection.get("https://example.com/balance")
```

### PLS004 — Extend a dispatcher without editing branches [OCP]

A dispatcher with three or more literal routes should use a handler registry. A new handler can then be added without changing the branch chain.

#### ✅ Compliant

```python
from collections.abc import Callable


def run_command(command_name: str, available_handlers: dict[str, Callable[[], str]]) -> str:
    return available_handlers[command_name]()
```

#### ❌ Violation

```python
from collections.abc import Callable


def run_command(
    command_name: str,
    list_handler: Callable[[], str],
    scale_handler: Callable[[], str],
    delete_handler: Callable[[], str],
) -> str:
    if command_name == "list":
        return list_handler()
    elif command_name == "scale":
        return scale_handler()
    elif command_name == "delete":
        return delete_handler()
    raise ValueError(command_name)
```

### PLS005 — Move static methods out of classes [SRP, team rule]

Do not use `@staticmethod`. Put independent behavior in a module function. This team rule is stricter than SRP itself.

#### ✅ Compliant

```python
def compute_total(values: list[int]) -> int:
    return sum(values)
```

#### ❌ Violation

```python
class InvoiceMath:
    @staticmethod
    def compute_total(values: list[int]) -> int:
        return sum(values)
```

### PLS006 — Use the method receiver [SRP, team rule]

A concrete method must use its instance or class receiver in the body. Move independent work to a module function.

#### ✅ Compliant

```python
class TextFormatter:
    def __init__(self, prefix_text: str) -> None:
        self.prefix_text = prefix_text

    def format_text(self, input_text: str) -> str:
        return self.prefix_text + input_text.strip()
```

#### ❌ Violation

```python
class TextFormatter:
    def format_text(self, input_text: str) -> str:
        return input_text.strip()
```

### PLS007 — Preserve override types [LSP]

A child method must accept all values accepted by the parent. Its return type must be at least as specific. Mypy checks this rule across files.

#### ✅ Compliant

```python
class ParentService:
    def process_value(self, input_value: object) -> None:
        self.last_value = input_value


class ChildService(ParentService):
    def process_value(self, input_value: object) -> None:
        self.last_value = input_value
```

#### ❌ Violation

```python
class ParentService:
    def process_value(self, input_value: object) -> None:
        self.last_value = input_value


class ChildService(ParentService):
    def process_value(self, input_value: str) -> None:
        self.last_value = input_value
```

### PLS008 — Put shared behavior in the base contract [OCP/LSP]

Do not check a list of child types before calling a method they share. Declare the method in the base contract.

#### ✅ Compliant

```python
class ParentShape:
    def draw_shape(self) -> str:
        return str(self)


def draw_some_shape(shape_object: ParentShape) -> str:
    return shape_object.draw_shape()
```

#### ❌ Violation

```python
class ParentShape:
    pass


class CircleShape(ParentShape):
    def draw_shape(self) -> str:
        return str(self)


class RectangleShape(ParentShape):
    def draw_shape(self) -> str:
        return str(self)


def draw_some_shape(shape_object: ParentShape) -> str:
    if isinstance(shape_object, CircleShape) or isinstance(shape_object, RectangleShape):
        return shape_object.draw_shape()
    return ""
```

### PLS009 — Inject a stored collaborator [DIP]

A class should not create a local class, store it, and call it from another method. Pass the collaborator in.

#### ✅ Compliant

```python
class MailNotifier:
    def send_message(self, message: str) -> str:
        return f"{self}: {message}"


class OrderService:
    def __init__(self, notifier: MailNotifier) -> None:
        self.notifier = notifier

    def complete_order(self, order_number: int) -> str:
        return self.notifier.send_message(str(order_number))
```

#### ❌ Violation

```python
class MailNotifier:
    def send_message(self, message: str) -> str:
        return f"{self}: {message}"


class OrderService:
    def __init__(self) -> None:
        self.notifier = MailNotifier()

    def complete_order(self, order_number: int) -> str:
        return self.notifier.send_message(str(order_number))
```

### PLS010 — Keep the parent precondition [LSP]

A child method must not reject an argument that the parent accepts. This rule checks a direct `if` that raises `ValueError` or `TypeError`.

#### ✅ Compliant

```python
class BalanceReader:
    def __init__(self, balance: int) -> None:
        self.balance = balance

    def read_balance(self, account_number: int) -> int:
        return account_number + self.balance


class PositiveReader(BalanceReader):
    def read_balance(self, account_number: int) -> int:
        return account_number + self.balance
```

#### ❌ Violation

```python
class BalanceReader:
    def __init__(self, balance: int) -> None:
        self.balance = balance

    def read_balance(self, account_number: int) -> int:
        return account_number + self.balance


class PositiveReader(BalanceReader):
    def read_balance(self, account_number: int) -> int:
        if account_number <= 0:
            raise ValueError("positive number required")
        return account_number + self.balance
```

### PLS011 — Require only the interface a client uses [ISP]

A client should accept a `Protocol` with only the methods it calls. This rule checks direct calls on a local protocol parameter.

#### ✅ Compliant

```python
from typing import Protocol


class SwitchableDevice(Protocol):
    def turn_on_device(self) -> None: ...


def activate_device(device_object: SwitchableDevice) -> None:
    device_object.turn_on_device()
```

#### ❌ Violation

```python
from typing import Protocol


class SmartHomeDevice(Protocol):
    def turn_on_device(self) -> None: ...
    def play_music_track(self, track_name: str) -> None: ...


def activate_device(device_object: SmartHomeDevice) -> None:
    device_object.turn_on_device()
```

## Output and limits

The checker reports `path:line:column: CODE message`. `PLS000` means the check failed, for example because Python could not be parsed or mypy could not run. It is not a SOLID rule. Other mypy errors appear as `MYPY [code]`. Mypy runs in strict mode and uses the project's configuration, including plugins and ignores.

To allow a finding, give a reason on its line:

```python
connection = httpx.Client()  # pylines-solid: ignore[PLS003] -- adapter owns this client
```

Unknown codes, missing reasons, and unused suppressions are errors. The [pre-commit hook](.pre-commit-hooks.yaml) needs access to the project's typing dependencies. See the [Justfile](Justfile) for development checks.

These rules detect specific patterns. They cannot prove full SOLID compliance. Review the reasons a class may change, the behavior of child classes, and the allowed import graph of each project. `PLS009` can flag a value object; inspect ownership before changing it. `PLS010` checks one guarded rejection pattern. `PLS011` skips clients that pass a protocol parameter to another function. `Any` and ignored mypy errors limit type checks. AST checks do not execute source files, but configured mypy plugins can run code.
