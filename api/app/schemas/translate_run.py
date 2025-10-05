from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import datetime
from .common import Entity

class TranslateRunIn(BaseModel):
    limit: int = 200
    source_lang: str = "ja_JP"
    target_lang: str = "en_US"
    entities: List[Entity] = ["field","view_common"]

class TranslateRunOut(BaseModel):
    processed: int
    failed: int

Entity = Literal["field", "view_common"]
State = Literal["pending", "translated", "ready_for_chroma", "done", "failed"]

class TranslateRunRequest(BaseModel):
    limit: int = 200
    source_lang: str = "ja_JP"
    target_lang: str = "en_US"
    entities: Optional[List[Entity]] = None  # 省略時は両方

class TranslateRow(BaseModel):
    natural_key: str
    entity: Entity
    model: Optional[str] = None
    label: Optional[str] = None
    purpose: Optional[str] = None
    translated_label: Optional[str] = None
    translated_purpose: Optional[str] = None
    status: Optional[State] = None
    updated_at: Optional[datetime] = None

class TranslateRunResult(BaseModel):
    picked: int
    translated: int
    failed: int
    samples: List[TranslateRow] = []