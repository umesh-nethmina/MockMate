"""CV parser tool: PDF bytes -> plain text in memory. The PDF itself is never stored (SRS 6.1)."""

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PAGES = 10


class CVParseError(ValueError):
    pass


@dataclass
class ParsedCV:
    text: str
    pages: int
    truncated: bool


def extract_text(data: bytes, max_chars: int) -> ParsedCV:
    if not data.startswith(b"%PDF"):
        raise CVParseError("This file is not a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise CVParseError("This PDF is password-protected. Please upload an unlocked copy.")
        pages = reader.pages[:MAX_PAGES]
        raw = "\n".join((page.extract_text() or "") for page in pages)
    except CVParseError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as e:
        raise CVParseError("We could not read this PDF. Try exporting it again from your editor.") from e

    text = re.sub(r"[ \t]+", " ", raw)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    text = "".join(ch for ch in text if ch == "\n" or ch.isprintable())
    if len(text) < 50:
        raise CVParseError("We could not find any text in this PDF. Is it a scanned image?")

    truncated = len(text) > max_chars
    return ParsedCV(text=text[:max_chars], pages=len(reader.pages), truncated=truncated)
