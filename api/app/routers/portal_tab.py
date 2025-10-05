# app/routers/tabs.py
from typing import Optional, Dict, Any, List, Literal
from fastapi import APIRouter, Query, Path, Body, status
from pydantic import BaseModel, Field

router = APIRouter(tags=["Portal Tab"])


# ---------- Schemas (Pydantic) ----------

SubviewPolicy = Literal["reference", "auto", "none"]

class CursorList(BaseModel):
    items: List[Dict[str, Any]]
    next_cursor: Optional[str] = None


class PortalTabBase(BaseModel):
    # 必須（POST時）
    view_id: Optional[int] = Field(None, ge=1)
    tab_key: Optional[str] = None

    # 表示ラベル
    tab_label_ja: Optional[str] = None
    tab_label_en: Optional[str] = None

    # モデル関連
    model: Optional[str] = None             # （親）表示便宜用
    child_model: Optional[str] = None
    child_link_field: Optional[str] = None

    # メタ／出自
    origin: Optional[str] = None
    module: Optional[str] = None
    is_codegen_target: Optional[bool] = False
    notes: Optional[str] = None
    github_url: Optional[str] = None

    # ビューモード（例: tree, form, tree,form）
    view_mode: Optional[str] = Field(
        None,
        description="例: 'tree', 'form', 'tree,form'"
    )

    # サブビュー生成方針
    subview_policy_tree: Optional[SubviewPolicy] = "reference"
    subview_policy_form: Optional[SubviewPolicy] = "reference"

    # Domain/Context
    use_domain: Optional[bool] = None
    domain_raw: Optional[str] = None
    use_context: Optional[bool] = None
    context_raw: Optional[str] = None

    # 権限/編集
    inline_edit: Optional[bool] = None
    allow_create_rows: Optional[bool] = None
    allow_delete_rows: Optional[bool] = None


class PortalTabCreate(PortalTabBase):
    view_id: int = Field(..., ge=1)
    tab_key: str = Field(..., min_length=1)


class PortalTabUpdate(PortalTabBase):
    # PATCHなので全て任意
    pass


class PortalTab(PortalTabBase):
    id: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PortalTabList(BaseModel):
    items: List[PortalTab]
    next_cursor: Optional[str] = None


# ---------- Routes ----------

@router.get("/portal/tab", summary="タブ一覧", response_model=PortalTabList)
def list_tabs(
    view_id: Optional[int] = Query(None, ge=1),
    tab_key: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None),
):
    """
    Keysetページング想定（cursor = Base64({"last_id": <int>})）。
    いまはモックとして空を返します。Repo接続時に置換。
    """
    return {"items": [], "next_cursor": None}


@router.post(
    "/portal/tab",
    summary="作成",
    status_code=status.HTTP_201_CREATED,
    response_model=PortalTab,
)
def create_tab(payload: PortalTabCreate = Body(...)):
    """
    モック実装：受け取った値をそのまま返す。
    Repo接続時にINSERT ... ON CONFLICT無しの通常INSERTへ置換。
    """
    return {
        "id": 1,
        **payload.model_dump(exclude_unset=True),
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


@router.get("/portal/tab/{id}", summary="取得", response_model=PortalTab)
def get_tab(id: int = Path(..., ge=1)):
    """
    モック実装：必要カラムをすべて含むサンプルを返却。
    """
    return {
        "id": id,
        "view_id": 1,
        "tab_key": "lines",
        "tab_label_ja": "明細",
        "tab_label_en": "Lines",
        "model": "sale.order",
        "child_model": "sale.order.line",
        "child_link_field": "order_id",
        "origin": "odoo",
        "module": "sale",
        "is_codegen_target": False,
        "notes": None,
        "github_url": None,
        "view_mode": "tree,form",
        "subview_policy_tree": "reference",
        "subview_policy_form": "reference",
        "use_domain": False,
        "domain_raw": None,
        "use_context": False,
        "context_raw": None,
        "inline_edit": False,
        "allow_create_rows": True,
        "allow_delete_rows": True,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


@router.patch("/portal/tab/{id}", summary="更新", response_model=PortalTab)
def update_tab(
    id: int = Path(..., ge=1),
    payload: PortalTabUpdate = Body(...),
):
    """
    モック実装：部分更新の体裁のみ（PATCH＝シャローマージ想定）。
    Repo接続時はJSONB列はDB側で `||` マージに置換。
    """
    # ここでは既存値の取得を省略し、入力をそのまま返す
    base = {
        "id": id,
        "view_id": 1,
        "tab_key": "lines",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    return {**base, **payload.model_dump(exclude_unset=True)}


@router.post(
    "/portal/tab/bulk_upsert",
    summary="複数タブの一括UPSERT",
    response_model=Dict[str, Any],
)
def bulk_upsert_tabs(payload: List[PortalTabCreate] = Body(...)):
    """
    モック実装：件数のみ返却。
    Repo接続時は (view_id, tab_key) を一意キーに ON CONFLICT DO UPDATE。
    """
    return {"updated": {"portal_tab": len(payload)}, "skipped": 0}
