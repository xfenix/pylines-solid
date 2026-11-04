# pylines-solid

Deterministic checks for SOLID patterns from [pylines](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md) and explicit team rules. AST checks and mypy type-contract checks run together by default. Mypy is installed with the package; no AI is used.

Supports Python 3.14 and 3.15. Run with the same Python version as the code being checked.

```sh
uv run --with 'pylines-solid @ git+https://github.com/xfenix/pylines-solid.git' pylines-solid .
```

Run in the project environment so mypy can see its dependencies and stubs. The package is not published to PyPI. Pin a Git commit when using it in CI. The repository also provides a [pre-commit hook](.pre-commit-hooks.yaml); its isolated environment needs the project's typing dependencies or a configured mypy `python_executable`.

## Checks

| Code / CLI tag | SOLID principle | Signal and suggested change |
|---|---|---|
| `PLS001 [LSP]` | [Liskov Substitution](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md#принцип-подстановки-лисков-liskov-substitution-principle-lsp) | An override always raises `NotImplementedError` instead of providing known local base behavior. Preserve the base contract or split the hierarchy. |
| `PLS002 [ISP]` | [Interface Segregation](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md#принцип-разделения-интерфейсов-interface-segregation-principle-isp) | A concrete method always raises `NotImplementedError`, suggesting an unsupported capability. Narrow the interface or declare a genuinely abstract method. |
| `PLS003 [SRP/DIP]` | [Single Responsibility](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md#принцип-единой-ответственности-single-responsibility-principle-srp) / [Dependency Inversion](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md#принцип-инверсии-зависимостей-dependency-inversion-principle-dip) | A class method creates an HTTP, Redis, database or Kafka client: it owns infrastructure setup and depends on a concrete factory. Separate setup from behavior and pass the client in. |
| `PLS004 [OCP]` | [Open/Closed](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md#принцип-открытостизакрытости-openclosed-principle-ocp) | A dispatcher maps ≥3 string values to distinct handlers. A registry allows new handlers without editing its branches. |
| `PLS005 [SRP]` | Single Responsibility — team rule | A method uses `@staticmethod`. Move independent behavior to a module function. The team's ban applies even to abstract/protocol declarations. |
| `PLS006 [SRP]` | Single Responsibility — cohesion signal | A concrete method body never uses its instance/class receiver. Move the behavior to a module function or the responsible object. |
| `PLS007 [LSP]` | Liskov Substitution | An override narrows accepted arguments, widens its result, breaks the call signature or narrows a writable attribute. Preserve the base type contract. |
| `PLS000` | Tool error; no SOLID principle | The check could not finish correctly: fix unreadable input, invalid Python/suppression or an unavailable type checker. |

Each SOLID diagnostic names the principle, explains the observed pattern and suggests a change. `Possible violation` means the reviewer must confirm that the principle applies to this design. For example:

```text
service.py:12:18: PLS003 [SRP/DIP] Possible violation: method owns infrastructure setup; separate setup from behavior and inject the client.
```

For example, `PLS003` flags construction inside a method:

```python
import httpx


class BalanceReader:
    def fetch_balance(self) -> httpx.Response:
        connection = httpx.Client()  # PLS003
        return connection.get("https://example.com/balance")
```

Pass the client from the code that owns its lifetime:

```python
import dataclasses

import httpx


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BalanceReader:
    connection: httpx.Client

    def fetch_balance(self) -> httpx.Response:
        return self.connection.get("https://example.com/balance")
```

Injected concrete client types are allowed. `Protocol` is not required for every dependency.

`PLS003` covers the shared SRP/DIP setup-and-injection examples in pylines: a user service creates PostgreSQL and Kafka connections itself. Supported factories include `asyncpg.connect`, `asyncpg.create_pool` and `aiokafka` producers/consumers. Dependency injection (DI) is the suggested technique: pass connections into the service to separate setup from user behavior. The `[SRP/DIP]` tag describes this narrow pattern; the checker does not verify every dependency abstraction required by DIP.

`PLS004` follows the command-dispatch example in pylines. Adding a command to a chain edits the dispatcher; a registry lets callers add a handler without rewriting it. A finding belongs to the first `if` or the `match` line. A fixed protocol can reasonably keep explicit branches; explain that choice with a suppression.

## Receiver use and type contracts

`PLS005` is the team's explicit ban on static methods. Python itself permits them; the ban is stricter than the general SRP definition. Both SRP findings point to the `def` line.

`PLS006` checks the body using Python's lexical scopes. A parameter name in the signature, a comment, a string or an annotation does not count. Attribute access, passing the receiver to another function, closure capture and `super()` count. A nested parameter or comprehension variable named `self` does not count as use of the outer receiver. Positional-only arguments, custom receiver names, `classmethod`, properties and async methods are supported.

LSP checks resolve type contracts across files on every normal run. The quickstart above includes them without additional flags or extras.

If `SpecialValue` inherits `GeneralValue`, these overrides illustrate the contract:

| Base method | Override | Result |
|---|---|---|
| `handle(value: GeneralValue)` | `handle(value: SpecialValue)` | LSP violation: accepts fewer inputs. |
| `handle(value: SpecialValue)` | `handle(value: GeneralValue)` | Compatible: accepts all base inputs. |
| `handle() -> SpecialValue` | `handle() -> GeneralValue` | LSP violation: promises a weaker result. |
| `handle() -> GeneralValue` | `handle() -> SpecialValue` | Compatible: returns a valid subtype. |

Mypy runs in strict mode with `override` and `mutable-override` enabled. It resolves imported hierarchies, aliases and generic substitutions. Other type errors are reported as `MYPY [code]`, so missing annotations or imports cannot silently make the run green. Missing mypy, invalid output or engine failure produces `PLS000`. Project mypy configuration applies, including plugins and configured ignores; plugins can execute code. Ordinary mypy errors use its `type: ignore[code]` mechanism; `PLS007` also supports the reasoned suppression below.

## Output and exceptions

Diagnostics use `path:line:column: CODE message`, with one-based positions. Exit codes are `0` for no findings, `1` for findings and `2` for input errors, invalid Python or invalid suppressions. Finding no Python files is an input error.

An intentional exception requires an explanation on the diagnostic's line:

```python
connection = httpx.Client()  # pylines-solid: ignore[PLS003] -- adapter owns this client's lifetime
```

Codes can be comma-separated. Unknown codes, missing reasons and unused suppressions fail. Text inside a string cannot suppress a finding.

Paths are checked recursively, with standard environment, build and cache directories excluded. Symbolic-link directories are not followed.

## Scope

These checks cover specific patterns across all five SOLID principles, not proof of compliance. SRP's reasons to change and OCP's future extension needs still require domain knowledge and review. No class-size or complexity metric is presented as an SRP verdict.

`PLS001`–`PLS003` cover module-level classes. Inherited methods are resolved only through same-file single inheritance. Imported hierarchies and nested classes are not resolved. Abstract methods and classes directly declaring `typing.Protocol` are exempt from refusal checks. A structural interface implementation can trigger `PLS002` without explicitly inheriting a protocol.

Client detection recognizes supported imported names and aliases, including imports inside a method. It checks method bodies, including constructors, but skips nested function bodies and module-level factories. Rebound or ambiguous names are conservatively skipped. There is no type inference or dynamic-call analysis; a clean run does not establish that all dependencies are injected.

`PLS004` scans the whole source tree, including functions and nested scopes. It requires the same name or attribute selector, distinct string literals and distinct named handlers. Each branch must contain just a call, a returned call, or a call followed by a bare return; awaited calls work too. Fallback branches are excluded. Guards, compound patterns/conditions, ranges, multi-step branches and dynamically computed selectors are skipped. The threshold of three routes is a review heuristic, not a definition of OCP. Git history is not analyzed.

`PLS005`/`PLS006` cover module-level classes and recognized decorator aliases. For receiver checks, abstract/Protocol declarations, stubs, special methods, known local overrides and methods with other decorators are skipped. Use `@typing.override` for imported contracts. Methods already reported for refusal or infrastructure construction are not reported again for missing receiver use. This is lexical use, not control-flow proof: dead code or rebinding can still hide independent behavior. Receiver use alone does not prove a single responsibility.

`PLS007` checks declared type contracts, not runtime preconditions, side effects or exception behavior. `Any`, ignored errors, missing type information and dynamic dispatch limit the guarantee. `--no-types` explicitly selects AST-only checks, which never import or execute inspected files and do not run `PLS007`.

Development commands and checks live in the [Justfile](Justfile). The [CI workflow](.github/workflows/check.yml) runs them on the supported interpreter versions.
