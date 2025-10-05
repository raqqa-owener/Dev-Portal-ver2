from pydantic import BaseModel
class WritebackViewCommonIn(BaseModel):
    mode: str = "skip_if_exists"
    overwrite: bool = False
