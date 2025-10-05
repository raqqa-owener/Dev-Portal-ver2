# api/app/config.py
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field
from sqlalchemy.engine import URL, make_url
import logging
import os

# === 翻訳関連（従来どおり：既存利用箇所の互換維持） ===
TRANSLATE_PROVIDER = os.getenv("TRANSLATE_PROVIDER", "dummy")  # openai|dummy
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL       = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL    = os.getenv("OPENAI_BASE_URL")  # Noneなら公式
TRANSLATE_SRC_LANG = os.getenv("TRANSLATE_SRC_LANG", "ja_JP")
TRANSLATE_TGT_LANG = os.getenv("TRANSLATE_TGT_LANG", "en_US")
TRANSLATE_LIMIT_DEF = int(os.getenv("TRANSLATE_LIMIT_DEF", "200"))


class Settings(BaseSettings):
    """
    アプリ全体の設定。
    - 既存のDB/基本設定はそのまま
    - フェーズG/H（パッケージング/Chroma upsert・Embedding）の設定値を追加
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 基本情報
    APP_NAME: str = "Dev Portal API"
    APP_ENV: str = "dev"
    DEBUG: bool = True

    # === DB 接続 ===
    # ローカル等で丸ごと使う場合のみ。K8s では DB_* を優先します。
    DATABASE_URL: Optional[str] = None

    # K8s/Secret/ConfigMap で渡す想定の分解値
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_NAME: str = "devportal"
    DB_USER: str = "dev"
    DB_PASSWORD: str = "dev"  # ※ 本番は Secret で

    # === Odoo（必要なら同様に扱う）===
    ODOO_DATABASE_URL: Optional[str] = None

    # === Chroma / Embeddings ===
    # H-slim: まずは OpenAI 固定のデフォルトで通す
    ALLOW_CHROMA_UPSERT: bool = (os.getenv("ALLOW_CHROMA_UPSERT", "true").lower() == "true")

    # 接続先：URL優先（互換のため CHROMA_BASE_URL は下の property で URL を返す）
    CHROMA_URL: str = os.getenv("CHROMA_URL", "http://chroma:8000")
    CHROMA_API_KEY: Optional[str] = os.getenv("CHROMA_API_KEY")
    CHROMA_TIMEOUT_S: int = int(os.getenv("CHROMA_TIMEOUT_S", "10"))

    EMBED_PROVIDER: str = os.getenv("EMBED_PROVIDER", "openai")
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-3-small")
    EMBED_DIMENSIONS: int = int(os.getenv("EMBED_DIMENSIONS", "1536"))
    EMBED_BATCH_SIZE: int = int(os.getenv("EMBED_BATCH_SIZE", "64"))

    # === フェーズG: パッケージング関連の設定（環境変数で上書き可能） ===
    # 例）PACK_TEXT_LIMIT=32768 PACK_SAMPLES_MAX=10 DEFAULT_COLLECTION_FIELD=portal_field_ja
    PACK_TEXT_LIMIT: int = int(os.getenv("PACK_TEXT_LIMIT", "16384"))  # 16 KiB 既定
    PACK_SAMPLES_MAX: int = int(os.getenv("PACK_SAMPLES_MAX", "5"))
    DEFAULT_COLLECTION_FIELD: str = os.getenv("DEFAULT_COLLECTION_FIELD", "portal_field_ja")
    DEFAULT_COLLECTION_VIEW_COMMON: str = os.getenv("DEFAULT_COLLECTION_VIEW_COMMON", "portal_view_common_ja")

    # 互換用（従来コードが参照していても壊さないため）
    @property
    def CHROMA_BASE_URL(self) -> str:
        # 旧来は host/port から合成していたが、H-slimでは URL を単一のソース・オブ・トゥルースにする
        return self.CHROMA_URL

    # 内部ヘルパー：最終的な SQLAlchemy URL を URL オブジェクトで返す
    def _normalized_database_url(self) -> URL:
        # 1) 明示された DATABASE_URL があれば（空文字は無効）まず検討
        raw = (self.DATABASE_URL or "").strip()
        if raw:
            try:
                u = make_url(raw).set(drivername="postgresql+psycopg2")
                # マスク（'***'）や未設定パスワードなら不採用
                if u.password not in (None, "", "***"):
                    return u
            except Exception:
                # 解析に失敗したら分解値にフォールバック
                pass

        # 2) K8s 前提：DB_* から生成（ここが既定の挙動）
        if self.DB_PASSWORD in (None, "", "***"):
            raise ValueError("DB_PASSWORD is not set or is a placeholder ('***').")

        return URL.create(
            "postgresql+psycopg2",
            username=self.DB_USER,
            password=self.DB_PASSWORD,  # URL.create がエスケープを面倒見ます
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )

    @computed_field
    @property
    def SQLALCHEMY_URL(self) -> str:
        """
        SQLAlchemy に渡す接続文字列。
        重要: パスワードを必ず含めるため、render_as_string(hide_password=False) を使用。
        """
        return self._normalized_database_url().render_as_string(hide_password=False)

    @computed_field
    @property
    def SQLALCHEMY_URL_OBJ(self) -> URL:
        """URL オブジェクト版（engine にそのまま渡してもOK）。"""
        return self._normalized_database_url()


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # 起動時ログ：Embedding と Chroma の主要設定を出力（キーやシークレットは出さない）
    logger = logging.getLogger("app.config")
    logger.info(
        "Embedding: provider=%s model=%s dim=%s batch=%s | Chroma: url=%s timeout_s=%s upsert_allowed=%s",
        s.EMBED_PROVIDER,
        s.EMBED_MODEL,
        s.EMBED_DIMENSIONS,
        s.EMBED_BATCH_SIZE,
        s.CHROMA_URL,
        s.CHROMA_TIMEOUT_S,
        s.ALLOW_CHROMA_UPSERT,
    )
    return s


# 既存コード互換：`from app.config import settings` で参照できるように
settings = get_settings()
