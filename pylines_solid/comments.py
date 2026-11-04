import io
import re
import tokenize
import typing

from pylines_solid.diagnostics import RULE_CODES, Diagnostic

IGNORE_PATTERN: typing.Final = re.compile(r"#\s*pylines-solid: ignore\[([A-Z0-9, ]+)\]\s+--\s+\S.*")


def apply_suppressions(source_text: str, findings: list[Diagnostic]) -> list[Diagnostic]:
    diagnostics: typing.Final = list(findings)
    for one_source_token in tokenize.generate_tokens(io.StringIO(source_text).readline):
        if one_source_token.type != tokenize.COMMENT or "pylines-solid:" not in one_source_token.string:
            continue
        ignore_match = IGNORE_PATTERN.fullmatch(one_source_token.string)
        ignored_codes = (
            frozenset(one_rule_code.strip() for one_rule_code in ignore_match.group(1).split(","))
            if ignore_match
            else frozenset()
        )
        matching_codes = frozenset(
            one_diagnostic.rule_code
            for one_diagnostic in findings
            if one_diagnostic.line_number == one_source_token.start[0]
        )
        if not ignored_codes or not ignored_codes <= RULE_CODES or not ignored_codes <= matching_codes:
            diagnostics.append(
                Diagnostic(
                    line_number=one_source_token.start[0],
                    column_number=one_source_token.start[1] + 1,
                    rule_code="PLS000",
                    message_text="Invalid or unused suppression; list matching rule codes and a reason after --.",
                ),
            )
            continue
        diagnostics[:] = [
            one_diagnostic
            for one_diagnostic in diagnostics
            if one_diagnostic.line_number != one_source_token.start[0] or one_diagnostic.rule_code not in ignored_codes
        ]
    return sorted(
        diagnostics,
        key=lambda diagnostic: (diagnostic.line_number, diagnostic.column_number, diagnostic.rule_code),
    )
