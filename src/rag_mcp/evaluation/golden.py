"""The golden set: questions with the page(s) that answer them, one JSON file per kind."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rag_mcp.errors import Code, RagError


class GoldenError(RagError):
    """The golden set is missing or malformed."""


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    kind: str
    question: str
    expected_uris: tuple[str, ...]


def load_golden(path: Path, uri_prefix: str) -> list[GoldenQuestion]:
    """Read one JSON file, or every `*.json` in a folder, in name order. `expected` paths are
    repo-relative and become stored uris by prefixing `uri_prefix`."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    questions: list[GoldenQuestion] = []
    for file in files:
        questions.extend(_read_file(file, uri_prefix))
    if not questions:
        raise GoldenError(Code.BAD_REQUEST, f"no golden questions found at {path}")
    return questions


def _read_file(file: Path, uri_prefix: str) -> list[GoldenQuestion]:
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
        return [
            GoldenQuestion(
                str(item["id"]),
                str(item["kind"]),
                str(item["question"]),
                tuple(uri_prefix + str(p) for p in item["expected"]),
            )
            for item in raw
        ]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise GoldenError(Code.BAD_REQUEST, f"cannot read golden set {file}: {error}") from error
