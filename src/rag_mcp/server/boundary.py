"""The one place where exceptions become MCP tool errors.

Inner layers raise named exceptions (`RagError` and its subclasses) and stay silent. Here each is
logged once and re-raised as a `ToolError("<code>: <sentence>")`, which the SDK returns to the
model as an error result. Anything unexpected is logged with its traceback and reported as
`internal`, so a tool that fails still answers the next call.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

import psycopg
from mcp.server.mcpserver.exceptions import ToolError

from rag_mcp.errors import Code, RagError

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def guarded(tool_name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    def decorate(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(function)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await function(*args, **kwargs)
            except RagError as error:
                log.warning("%s refused: %s", tool_name, error)
                raise ToolError(str(error)) from error
            except psycopg.Error as error:
                log.exception("%s: database error", tool_name)
                message = f"{Code.INTERNAL}: the database is unavailable, retry shortly"
                raise ToolError(message) from error
            except Exception as error:  # the single catch-all, by design: see the module docstring
                log.exception("%s: unexpected error", tool_name)
                raise ToolError(f"{Code.INTERNAL}: unexpected error, see the server log") from error

        return wrapper

    return decorate
