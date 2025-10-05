from pydantic import BaseModel
from .common import Summary

class StatusSummary(BaseModel):
    summary: Summary
