"""Turn an HTML page into plain text with paragraph breaks, using only the standard library."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

# Menus and footers would otherwise be ingested with every page of a documentation site.
_SKIPPED = frozenset({"script", "style", "noscript", "template", "svg", "nav", "footer"})
_BLOCK = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "table", "pre", "section", "article", "nav",
     "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "dd", "dt", "hr"}
)  # fmt: skip
_MANY_BLANK_LINES = re.compile(r"\n\s*\n(\s*\n)+")


@dataclass(frozen=True)
class HtmlText:
    title: str
    text: str


def html_to_text(html: str) -> HtmlText:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = _MANY_BLANK_LINES.sub("\n\n", "".join(extractor.parts)).strip()
    return HtmlText(title=" ".join(extractor.title.split()), text=text)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self.parts.append("\n" if tag == "br" else "\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)
