# api/app/db.py
import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session as SASession

logger = logging.getLogger(__name__)

# ---- settings の取り出し（settings or get_settings のどちらにも対応） ----
try:
    from app.config import settings as _settings  # 推奨：モジュールグローバル settings
except Exception:
    _settings = None

if _settings is not None:
    settings = _settings
else:
    try:
        from app.config import get_settings  # 互換: 関数から取得
    except Exception:  # 極力起動はできるフォールバック
        get_settings = None  # type: ignore

    if get_settings:
        settings = get_settings()  # type: ignore
    else:
        class _Fallback:
            SQLALCHEMY_URL = "postgresql://postgres:postgres@postgres:5432/postgres"
            DATABASE_URL = SQLALCHEMY_URL
            DB_PASSWORD: Optional[str] = "postgres"
        settings = _Fallback()  # type: ignore

# 接続URLは SQLALCHEMY_URL を優先、無ければ DATABASE_URL
SQL_URL = getattr(settings, "SQLALCHEMY_URL", None) or getattr(settings, "DATABASE_URL", None)
if not SQL_URL:
    SQL_URL = "postgresql://postgres:postgres@postgres:5432/postgres"

# ---- SQLAlchemy Engine / Session ----
engine = create_engine(
    SQL_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=1800,
)

# ログ用にパスワードは伏せる
_db_password = getattr(settings, "DB_PASSWORD", None)
masked = SQL_URL
try:
    if _db_password and _db_password in SQL_URL:
        masked = SQL_URL.replace(_db_password, "***")
except Exception:
    pass
logger.info("DB connecting to %s", masked)

# expire_on_commit=False を推奨（コミット後も参照しやすい）
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

def get_session() -> Generator[SASession, None, None]:
    """
    FastAPI の Depends 用：リクエスト毎に 1 セッション。
    成功で commit / 失敗で rollback。
    """
    db: SASession = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# alias: ルーター側で from app.db import Session として使えるように
Session = SASession

def ping() -> bool:
    """DB到達性の簡易チェック"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("DB ping failed: %s", e)
        return False

# ---- 互換: session_scope（旧コードが cursor を期待する場合に備える） ----
# 可能なら utils 側の実装を再輸出
try:
    from app.utils.cursor import session_scope as _session_scope  # type: ignore
    session_scope = _session_scope  # re-export
except Exception:
    # psycopg があればそれで実装、無ければ SQLAlchemy の raw_connection で代替
    try:
        import psycopg  # psycopg v3
        def _conn_url() -> str:
            return getattr(settings, "DATABASE_URL", None) or SQL_URL  # type: ignore

        @contextmanager
        def session_scope():
            """
            旧コード互換: psycopg の cursor を yield。
            成功で commit / 失敗で rollback。
            """
            conn = engine.raw_connection()
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                try:
                    cur.close()
                finally:
                    conn.close()
    except Exception:
        @contextmanager
        def session_scope():
            """
            psycopg が無い環境向けフォールバック。
            SQLAlchemy の raw_connection から DB-API cursor を返す。
            """
            conn = engine.raw_connection()
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                try:
                    cur.close()
                finally:
                    conn.close()

__all__ = [
    "engine",
    "SessionLocal",
    "Session",
    "get_session",
    "ping",
    "session_scope",  # 旧コード互換
]
