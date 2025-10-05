from typing import List
from pydantic import BaseModel


class BootstrapViewRequest(BaseModel):
    action_xmlids: List[str]
    set_primary_from_common: bool = True


class BootstrapResult(BaseModel):
    created: int = 0
    skipped: int = 0