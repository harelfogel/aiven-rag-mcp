"""The closed set of error codes a client can branch on, and the base exception that carries one."""

from __future__ import annotations

from enum import StrEnum


class Code(StrEnum):
    BAD_REQUEST = "bad_request"  # the input is wrong and retrying it unchanged will not help
    NOT_FOUND = "not_found"
    TOO_LARGE = "too_large"
    UNREACHABLE = "unreachable"  # network or DNS failed; retrying later may help
    INTERNAL = "internal"


class RagError(Exception):
    """Every error we raise on purpose; the MCP boundary turns it into a ToolError."""

    def __init__(self, code: Code, message: str) -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()}"
