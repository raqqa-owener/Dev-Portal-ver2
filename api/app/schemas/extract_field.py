from typing import List, Optional, Literal
from pydantic import BaseModel, model_validator

UpsertMode = Literal['upsert', 'skip_existing', 'upsert_if_changed']

class ExtractFieldRequest(BaseModel):
    models: Optional[List[str]] = None
    fields: Optional[List[str]] = None
    mode: UpsertMode = 'upsert_if_changed'

    @model_validator(mode='after')
    def _any_required(self):
        if not self.models and not self.fields:
            raise ValueError("At least one of models or fields is required")
        return self
