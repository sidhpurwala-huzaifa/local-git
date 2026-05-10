"""Render Markdown to sanitized HTML (local repo files; treat as untrusted)."""

from __future__ import annotations

import markdown
import nh3

_MD_EXTENSIONS = [
    "fenced_code",
    "tables",
    "nl2br",
    "sane_lists",
]


def is_markdown_path(path: str) -> bool:
    base = path.rsplit("/", 1)[-1].lower()
    return base.endswith(".md") or base.endswith(".markdown")


def render_markdown(text: str) -> str:
    raw = markdown.markdown(
        text,
        extensions=_MD_EXTENSIONS,
        output_format="html",
    )
    return nh3.clean(raw)
