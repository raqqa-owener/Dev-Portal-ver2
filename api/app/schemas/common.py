from pydantic import BaseModel
from typing import Literal
from typing import List

Lang = Literal["ja", "en"]
Entity = Literal["field", "view_common"]

class NaturalKey(BaseModel):
    entity: Entity
    key: str

class Summary(BaseModel):
    pending: int
    translated: int
    queued: int
    upserted: int

class Problem(BaseModel):
    type: str | None = None
    title: str
    detail: str | None = None
    status: int


class ExtractResultDetail(BaseModel):
    natural_key: str
    reason: str  # one of: picked/inserted/updated/skipped_no_ja/skipped_has_en/skipped_no_change/skipped_not_found


class ExtractResult(BaseModel):
    picked: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_no_ja: int = 0
    skipped_has_en: int = 0
    skipped_no_change: int = 0
    skipped_not_found: int = 0
    details: List[ExtractResultDetail] = []
