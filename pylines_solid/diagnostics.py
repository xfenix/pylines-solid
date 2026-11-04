import dataclasses
import typing


@typing.final
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Diagnostic:
    line_number: int
    column_number: int
    rule_code: str
    message_text: str


RULE_CODES: typing.Final = frozenset({"PLS001", "PLS002", "PLS003", "PLS004"})
