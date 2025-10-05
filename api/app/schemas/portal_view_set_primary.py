from typing import Literal, Optional
from pydantic import BaseModel, model_validator

# 主ビュー設定の指定方法:
#  1) view_id だけを指定  例: {"view_id": 123}
#  2) common_id + view_type を指定 例: {"common_id": 10, "view_type": "list"}
#
# 両方を同時に渡す/どちらも欠ける → バリデーションエラー

ViewType = Literal[
    "form", "kanban", "list", "calendar", "search",
    "graph", "pivot", "dashboard", "tree", "map"
]

class SetPrimaryRequest(BaseModel):
    view_id: Optional[int] = None
    common_id: Optional[int] = None
    view_type: Optional[ViewType] = None

    @model_validator(mode="after")
    def _check_selector(self) -> "SetPrimaryRequest":
        has_view_id = self.view_id is not None
        has_pair = (self.common_id is not None) and (self.view_type is not None)

        if not has_view_id and not has_pair:
            raise ValueError("Either 'view_id' OR both 'common_id' and 'view_type' must be provided.")
        if has_view_id and (self.common_id is not None or self.view_type is not None):
            raise ValueError("Provide only 'view_id' OR ('common_id' + 'view_type'), not both.")
        return self
