"""Article text cleaning: strip HTML, boilerplate, and tracking junk."""

import re

from bs4 import BeautifulSoup

_BOILERPLATE_PATTERNS = [
    re.compile(r"subscribe to our newsletter", re.I),
    re.compile(r"sign up for .{0,40}(newsletter|briefing)", re.I),
    re.compile(r"all rights reserved", re.I),
    re.compile(r"follow us on", re.I),
    re.compile(r"advertisement", re.I),
    re.compile(r"read more:?\s*$", re.I),
    re.compile(r"click here", re.I),
    re.compile(r"share this article", re.I),
]

_REMOVED_TAGS = ["script", "style", "nav", "aside", "footer", "header", "form", "iframe", "noscript"]


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_REMOVED_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return text


def clean_text(raw: str) -> str:
    """Clean raw article HTML/text into readable plain text."""
    if not raw:
        return ""
    text = html_to_text(raw) if "<" in raw and ">" in raw else raw
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) < 4:
            continue
        if any(p.search(line) for p in _BOILERPLATE_PATTERNS):
            continue
        lines.append(line)
    # Collapse duplicate consecutive lines (common feed boilerplate)
    deduped = [line for i, line in enumerate(lines) if i == 0 or line != lines[i - 1]]
    return "\n".join(deduped)
