from base64 import urlsafe_b64encode, urlsafe_b64decode
import json
from typing import Optional
from contextlib import contextmanager
from typing import Generator, TypeAlias
import psycopg
from psycopg.rows import dict_row
from app.config import settings


def encode_last_id_cursor(last_id: int) -> str:
    return urlsafe_b64encode(json.dumps({"last_id": int(last_id)}).encode()).decode()

def decode_last_id_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        d = json.loads(urlsafe_b64decode(cursor.encode()).decode())
        return int(d.get("last_id", 0))
    except Exception:
        return 0
    
Session: TypeAlias = psycopg.Connection

def get_session() -> Generator[Session, None, None]:
    """
    FastAPI の Depends 用。使い終わりで確実に close。
    """
    conn = psycopg.connect(settings.DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

def get_cursor(conn: Session):
    """必要なら DictRow で cursor を取りたい時に。"""
    return conn.cursor(row_factory=dict_row)