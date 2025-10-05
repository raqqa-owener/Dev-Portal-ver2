# api/app/schemas/portal_view_common.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

# ---- Core models (OpenAPI 設計に準拠) ----

class PortalViewCommon(BaseModel):
    id: int
    action_xmlid: str
    action_name: Optional[str] = None
    model: str
    model_label: Optional[str] = None
    model_table: str
    view_types: List[str] = Field(default_factory=list)
    primary_view_type: str
    help_ja_text: Optional[str] = None
    help_en_text: Optional[str] = None
    ai_purpose: Optional[str] = None
    ai_purpose_i18n: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
# ルーターが期待する "Out" 形（実体は同じでOK）
PortalViewCommonOut = PortalViewCommon

class PortalViewCommonUpdate(BaseModel):
    help_ja_text: Optional[str] = None
    ai_purpose: Optional[str] = None
    ai_purpose_i18n: Optional[Dict[str, Any]] = None
    primary_view_type: Optional[str] = None
    view_types: Optional[List[str]] = None

class PortalViewCommonList(BaseModel):
    items: List[PortalViewCommon] = Field(default_factory=list)
    next_cursor: Optional[str] = None

class PortalViewCommonCreate(BaseModel):
    # OpenAPIのPOSTボディに合わせた作成用スキーマ
    action_xmlid: str
    model: str
    action_name: Optional[str] = None
    model_label: Optional[str] = None
    model_table: Optional[str] = None
    view_types: Optional[List[str]] = None
    primary_view_type: Optional[str] = None
    help_ja_text: Optional[str] = None
    help_en_text: Optional[str] = None
    ai_purpose: Optional[str] = None
    ai_purpose_i18n: Optional[Dict[str, Any]] = None

# ---- Re-exports so routers can import everything from here ----
# ルータが1ファイルから全記号を import できるように再輸出します。
try:
    from .imports import ImportViewCommonRequest, ImportResult  # type: ignore
except Exception:
    pass

try:
    from .bootstrap_view import BootstrapViewRequest, BootstrapResult  # type: ignore
except Exception:
    pass

try:
    from .extract_view_common import ExtractViewCommonRequest, ExtractResult  # type: ignore
except Exception:
    pass
