from pydantic import BaseModel
class WritebackFieldIn(BaseModel):
    mode: str = "skip_if_exists"
    overwrite: bool = False
