"""PDF → text for statement parsing.

Bank PDFs differ in how they place text. ICICI e-statements, for example,
draw every glyph individually, and a naive extractor emits text spaced apart
letter by letter ("0 1-09 -202 6") that no parser can read. So we extract the
text several ways and let the caller keep whichever one parses best (the
parser can tell: a bank statement's running balances must add up).

Methods:
- chars:   pdfminer characters regrouped into rows by position, spaces only
           where there is a real gap
- pdfminer: pdfminer's own layout analysis
- plain / layout: pypdf's two modes

Password-protected PDFs (RC4/AES) are decrypted in pure Python.
"""

import io
import logging
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.high_level import extract_text as pdfminer_text
from pdfminer.layout import LAParams, LTChar, LTPage
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError

log = logging.getLogger("moneymap.statements")


class StatementError(Exception):
    code = "error"


class PasswordRequired(StatementError):
    code = "password_required"


class WrongPassword(StatementError):
    code = "wrong_password"


class NoText(StatementError):
    code = "no_text"


MIN_CHARS_PER_PAGE = 40  # below this the PDF is probably a scanned image


def _chars(obj):
    if isinstance(obj, LTChar):
        yield obj
        return
    try:
        for child in obj:
            yield from _chars(child)
    except TypeError:
        return


def page_lines(page: LTPage) -> list[str]:
    """Rows by vertical position; within a row, a space where the gap between
    glyphs is wider than a fraction of the glyph size, a wide gap = column."""
    chars = [c for c in _chars(page) if c.get_text().strip()]
    if not chars:
        return []
    chars.sort(key=lambda c: (-(c.y0 + c.y1) / 2, c.x0))
    sizes = sorted(c.size for c in chars if c.size > 0) or [10.0]
    size = sizes[len(sizes) // 2]
    tol = max(1.5, size * 0.4)
    rows: list[list[LTChar]] = []
    centre = None
    for c in chars:
        y = (c.y0 + c.y1) / 2
        if centre is None or abs(y - centre) > tol:
            rows.append([c])
            centre = y
        else:
            rows[-1].append(c)
    lines = []
    for row in rows:
        row.sort(key=lambda c: c.x0)
        out: list[str] = []
        prev = None
        for c in row:
            if prev is not None:
                gap = c.x0 - prev.x1
                if gap > size * 1.2:
                    out.append("   ")
                elif gap > size * 0.18:
                    out.append(" ")
            out.append(c.get_text())
            prev = c
        lines.append("".join(out).rstrip())
    return [ln for ln in lines if ln.strip()]


def _open_check(data: bytes, password: str | None) -> list:
    try:
        return list(extract_pages(io.BytesIO(data), password=password or "", laparams=None))
    except PDFPasswordIncorrect:
        if not password:
            raise PasswordRequired("This PDF is password-protected.") from None
        raise WrongPassword("That password didn't open the PDF.") from None
    except (PDFSyntaxError, ValueError) as e:
        raise StatementError(f"This file isn't a readable PDF ({e}).") from None


def extract_candidates(path: Path, password: str | None = None) -> list[tuple[str, str]]:
    """[(method, text), ...] — every method that produced usable text."""
    data = Path(path).read_bytes()
    pages = _open_check(data, password)
    out: list[tuple[str, str]] = [("chars", "\n".join("\n".join(page_lines(p)) for p in pages))]
    try:
        out.append(("pdfminer", pdfminer_text(io.BytesIO(data), password=password or "", laparams=LAParams())))
    except Exception as e:  # noqa: BLE001 — a failed method is just skipped
        log.info("pdfminer layout extraction failed: %s", e)
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt(password or "")
        for mode in ("plain", "layout"):
            out.append((mode, "\n".join((p.extract_text(extraction_mode=mode) or "") for p in reader.pages)))
    except Exception as e:  # noqa: BLE001
        log.info("pypdf extraction failed: %s", e)
    usable = [(m, t) for m, t in out if len(t.strip()) >= MIN_CHARS_PER_PAGE * max(1, len(pages))]
    if not usable:
        raise NoText("No text could be read from this PDF — it may be a scanned image.")
    return usable


def extract_text(path: Path, password: str | None = None) -> str:
    """The first usable extraction (chars method). Prefer extract_candidates +
    choosing by parse quality."""
    return extract_candidates(path, password)[0][1]
