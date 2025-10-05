# api/app/schemas/chroma_upsert.py
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ChromaUpsertRequest(BaseModel):
    """POST /chroma/upsert request body."""
    # 余剰プロパティ拒否
    model_config = ConfigDict(extra="forbid")

    collections: Optional[List[str]] = Field(
        default=None,
        description="対象コレクション（未指定は全件）"
    )
    limit: int = Field(
        default=1000,
        ge=1,
        le=5000,
        description="最大処理件数（1..5000、既定: 1000）"
    )
    dry_run: bool = Field(
        default=False,
        description="true の場合は件数レポートのみ（DB/Chroma変更なし）"
    )


class ChromaUpsertError(BaseModel):
    """Upsert失敗時の1件分のエラー情報。"""
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    reason: str


class ChromaUpsertResult(BaseModel):
    """POST /chroma/upsert の結果。"""
    model_config = ConfigDict(extra="forbid")

    processed: int
    upserted: int
    skipped: int
    failed: int
    errors: List[ChromaUpsertError] = Field(default_factory=list)
