from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from typing import Any

from .base import Tool, object_schema


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip = False
        if tag in {"p", "br", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch a URL and return extracted text or raw HTML."
    read_only = True

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "url": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["text", "raw"]},
                "max_chars": {"type": "integer"},
            },
            required=["url"],
        )

    def execute(self, url: str, mode: str = "text", max_chars: int = 12000, **_: Any) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "prismax/0.1"})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
        if mode == "raw":
            return raw[:max_chars]
        parser = TextExtractor()
        parser.feed(raw)
        return parser.text()[:max_chars]
