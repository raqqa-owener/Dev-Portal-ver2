# このファイルは /chroma/package と /chroma/docs で使う Pydantic スキーマ定義をまとめています。
# - ChromaPackageRequest/Result: パッケージング入力・結果
# - ChromaDoc/ChromaDocsList: portal_chroma_doc の一覧返却

from __future__ import annotations
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

Lang = Literal["ja", "en"]
Entity = Literal["field", "view_common"]

class CursorList(BaseModel):
    items: list
    next_cursor: Optional[str] = None

class ChromaPackageRequest(BaseModel):
    entities: Optional[List[Entity]] = Field(default_factory=lambda: ["field", "view_common"])  # default
    lang: Lang = Field(default="ja")
    collections: Optional[Dict[str, str]] = Field(
        default_factory=lambda: {"field": "portal_field_ja", "view_common": "portal_view_common_ja"}
    )
    limit: int = Field(default=500, ge=1, le=5000)

class ChromaPackageSample(BaseModel):
    doc_id: str
    collection: str
    model: Optional[str] = None
    status: Literal["queued", "upserted", "failed"]

class ChromaPackageResult(BaseModel):
    queued: int = 0
    skipped_no_change: int = 0
    failed: int = 0
    samples: List[ChromaPackageSample] = Field(default_factory=list)

class ChromaDoc(BaseModel):
    doc_id: str
    natural_key: str
    lang: Lang
    collection: str
    doc_text: str
    entity: Entity
    model: Optional[str] = None
    model_table: Optional[str] = None
    field_name: Optional[str] = None
    action_xmlid: Optional[str] = None
    target: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    status: Literal["queued", "upserted", "failed"] = "queued"
    updated_at: Optional[str] = None

class ChromaDocsList(CursorList):
    items: List[ChromaDoc]
