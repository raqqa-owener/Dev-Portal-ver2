from typing import List, Optional, Literal
from pydantic import BaseModel, model_validator

UpsertMode = Literal['upsert', 'skip_existing', 'upsert_if_changed']
Target = Literal['ai_purpose', 'help']

class ExtractViewCommonRequest(BaseModel):
    action_xmlids: List[str]
    targets: Optional[List[Target]] = None
    mode: UpsertMode = 'upsert_if_changed'

    @model_validator(mode='after')
    def _default_targets(self):
        if not self.targets:
            self.targets = ['ai_purpose', 'help']
        return self
