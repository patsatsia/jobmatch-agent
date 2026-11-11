import re

from bs4 import BeautifulSoup

_SPACES = re.compile(r"[ \t\xa0]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def html_to_text(html: str) -> str:
    """Turn an HTML job description into clean plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    text = "\n".join(lines)
    return _BLANK_LINES.sub("\n\n", text).strip()
