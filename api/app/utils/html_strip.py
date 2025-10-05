# strip HTML
import re
from html import unescape

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\x0b\f\r]+")


def strip_html(value: str | None) -> str:
    if not value:
        return ''
    # unescape entities then drop tags
    s = unescape(str(value))
    s = _TAG_RE.sub('', s)
    return s


def normalize_help_text(value: str | None, *, max_consecutive_newlines: int = 2) -> str:
    """HTML除去 → 連続空白の1化 → 改行正規化（連続改行は最大N）"""
    s = strip_html(value)
    # Normalize CRLF/CR to LF
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    # Collapse horizontal whitespace (not newlines)
    s = _WS_RE.sub(' ', s)
    # Trim each line and drop surrounding blank space
    lines = [ln.strip() for ln in s.split('\n')]
    s = '\n'.join(lines).strip()
    # Limit consecutive blank lines
    if max_consecutive_newlines is not None and max_consecutive_newlines >= 0:
        out_lines = []
        blank_run = 0
        for ln in s.split('\n'):
            if ln == '':
                blank_run += 1
            else:
                blank_run = 0
            if ln != '' or blank_run <= max_consecutive_newlines:
                out_lines.append(ln)
        s = '\n'.join(out_lines).strip()
    return s