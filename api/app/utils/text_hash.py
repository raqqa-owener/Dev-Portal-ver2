# text hashing for change detection
import hashlib


def sha256_text(text: str) -> str:
    if text is None:
        text = ''
    if not isinstance(text, (str, bytes)):
        text = str(text)
    if isinstance(text, str):
        text = text.encode('utf-8')
    return hashlib.sha256(text).hexdigest()