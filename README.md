# pylines-solid

Small deterministic checks for concrete SOLID patterns from [pylines](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md). Uses Python's AST, without AI or runtime dependencies. It reads source files; it never imports or executes them.

Supports Python 3.14 and 3.15. Run with the same Python version as the code being checked.

```sh
uvx --from git+https://github.com/xfenix/pylines-solid.git pylines-solid .
```

The package is not published to PyPI. Pin a Git commit when using it in CI. The repository also provides a [pre-commit hook](.pre-commit-hooks.yaml).

## Checks

| Code | Pattern |
|---|---|
| `PLS001` | A method refuses a known local inherited capability with an unconditional `NotImplementedError`. |
| `PLS002` | Another concrete method unconditionally raises `NotImplementedError`: a candidate for splitting the interface or declaring the method abstract. |
| `PLS003` | SRP/DI: a class method owns infrastructure setup, constructing a recognized HTTP, Redis, database or Kafka client instead of receiving it. |
| `PLS004` | OCP: an `if/elif` or `match` dispatcher maps three or more string values to distinct handlers; consider a handler registry. |
| `PLS000` | Input or suppression error. |

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

`PLS003` also covers the SRP example in pylines: a user service creates PostgreSQL and Kafka connections itself. Supported factories include `asyncpg.connect`, `asyncpg.create_pool` and `aiokafka` producers/consumers. Passing connections into the service separates setup from user behavior. This is one check spanning SRP and DI, not two duplicate diagnostics.

`PLS004` follows the command-dispatch example in pylines. Adding a command to a chain edits the dispatcher; a registry lets callers add a handler without rewriting it. A finding belongs to the first `if` or the `match` line. A fixed protocol can reasonably keep explicit branches; explain that choice with a suppression.

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

Development commands and checks live in the [Justfile](Justfile). The [CI workflow](.github/workflows/check.yml) runs them on the supported interpreter versions.
