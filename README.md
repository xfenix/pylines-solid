# pylines-solid

Small deterministic checks for concrete SOLID patterns from [pylines](https://github.com/community-of-python/pylines/blob/cfaf7a4/solid.md). Uses Python's AST, without AI or runtime dependencies. It reads source files; it never imports or executes them.

Requires Python 3.12 or newer. Run with the same Python version as the code being checked.

```sh
uvx --from git+https://github.com/xfenix/pylines-solid.git pylines-solid .
```

The package is not published to PyPI. Pin a Git commit when using it in CI. The repository also provides a [pre-commit hook](.pre-commit-hooks.yaml).

## Checks

| Code | Pattern |
|---|---|
| `PLS001` | A method refuses a known local inherited capability with an unconditional `NotImplementedError`. |
| `PLS002` | Another concrete method unconditionally raises `NotImplementedError`: a candidate for splitting the interface or declaring the method abstract. |
| `PLS003` | A class method constructs a recognized HTTP, Redis or database client instead of receiving it. |
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

## Output and exceptions

Diagnostics use `path:line:column: CODE message`, with one-based positions. Exit codes are `0` for no findings, `1` for findings and `2` for input errors, invalid Python or invalid suppressions. Finding no Python files is an input error.

An intentional exception requires an explanation on the diagnostic's line:

```python
connection = httpx.Client()  # pylines-solid: ignore[PLS003] -- adapter owns this client's lifetime
```

Codes can be comma-separated. Unknown codes, missing reasons and unused suppressions fail. Text inside a string cannot suppress a finding.

Paths are checked recursively, with standard environment, build and cache directories excluded. Symbolic-link directories are not followed.

## Scope

These checks report syntax patterns, not proof of SOLID compliance. SRP and OCP remain outside this tool; use existing complexity checks and review.

Analysis covers module-level classes. Inherited methods are resolved only through same-file single inheritance. Imported hierarchies and nested classes are not resolved. Abstract methods and classes directly declaring `typing.Protocol` are exempt from refusal checks. A structural interface implementation can trigger `PLS002` without explicitly inheriting a protocol.

Client detection recognizes supported imported names and aliases, including imports inside a method. It checks method bodies, including constructors, but skips nested function bodies and module-level factories. Rebound or ambiguous names are conservatively skipped. There is no type inference or dynamic-call analysis; a clean run does not establish that all dependencies are injected.

Development commands and checks live in the [Justfile](Justfile). The [CI workflow](.github/workflows/check.yml) runs them on the supported interpreter versions.
