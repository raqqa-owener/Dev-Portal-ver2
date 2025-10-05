
from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


__all__ = [
    "ImportFieldRequest",
    "ImportViewCommonRequest",
    "ImportResult",
]

class ImportModelRequest(BaseModel):
    models: List[str]
    scaffold: bool = Field(default=True)


class ImportFieldRequest(BaseModel):
    model: str = Field(..., description="技術名 e.g. 'stock.picking'")
    fields: Optional[List[str]] = Field(default=None, description="取り込むフィールド名の配列。未指定なら全件")



class ImportViewCommonRequest(BaseModel):
    action_xmlids: List[str] = Field(..., description="取り込み対象の action_xmlid 群")


class ImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = Field(default_factory=list)