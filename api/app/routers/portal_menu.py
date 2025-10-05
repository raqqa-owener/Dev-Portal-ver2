# app/routers/menu.py
from typing import Dict, Any, Optional, List, Literal
from fastapi import APIRouter, Body, Path, Query, status
from pydantic import BaseModel, Field

router = APIRouter(tags=["Portal Menu"])

# -------------------------------------------------------
# API ↔ DB マッピングメモ（現DDLとの差分を明示）
# API: menu_id                -> （将来）ir_ui_menu.id 等の参照値（現DDLに列なし）
# API: menu_xml_id            -> （将来）menu_key へ寄せる or 新規列 menu_xml_id
# API: menu_path_i18n (json)  -> （将来）label_i18n を階層結合で表現 or 新規列
# API: sequence               -> DB: sequence
# API: action_type            -> （将来）新規列 action_type
# API: action_xml_id          -> （将来）新規列 action_xml_id
# API: action_label_i18n      -> （将来）新規列 action_label_i18n (jsonb)
# API: target_model           -> DB: model（同義・名称差）
# API: view_mode              -> （将来）新規列 view_mode
# API: initial_domain_expr    -> （将来）新規列 initial_domain_expr
# API: initial_domain_i18n    -> （将来）新規列 initial_domain_i18n (jsonb)
# API: origin                 -> DB: origin（既存）
# API: origin_module          -> （将来）新規列 origin_module
# API: code_present           -> （将来）新規列 code_present (bool)
# API: code_github_url        -> DB: notes とは別に新規列 code_github_url
# API: notes                  -> DB: notes
# API: created_at/updated_at  -> DB: created_at/updated_at（トリガで更新）
# 一覧の自然キー/識別子は暫定で id（主キー）。本実装はモック。
# -------------------------------------------------------

ActionType = Literal["act_window", "report", "client", "server_action", "url", "other"]
OriginType = Literal["standard", "module", "studio", "portal", "unknown"]

class MenuBase(BaseModel):
    # 識別関連
    menu_id: Optional[int] = Field(None, description="参照: ir_ui_menu.id など")
    menu_xml_id: Optional[str] = Field(None, description="<module>.<name>")

    # 表示系
    menu_path_i18n: Optional[Dict[str, str]] = Field(
        None, description='例 {"ja_JP":"販売/受注/見積", "en_US":"Sales/Orders/Quotations"}'
    )
    sequence: Optional[int] = Field(None, ge=0, description="同階層の表示順")

    # アクション
    action_type: Optional[ActionType] = None
    action_xml_id: Optional[str] = None
    action_label_i18n: Optional[Dict[str, str]] = None
    target_model: Optional[str] = Field(None, description="例: sale.order（URL/Client等はNULL可）")
    view_mode: Optional[str] = Field(None, description="例: tree,form")

    # 初期ドメイン
    initial_domain_expr: Optional[str] = Field(None, description="例: [('state','=','draft')]")
    initial_domain_i18n: Optional[Dict[str, str]] = None

    # メタ
    origin: Optional[OriginType] = "unknown"
    origin_module: Optional[str] = None
    code_present: Optional[bool] = None
    code_github_url: Optional[str] = None
    notes: Optional[str] = None

class MenuCreate(MenuBase):
    # 最小必須は menu_xml_id のみ（他は任意で後から追記可）
    menu_xml_id: str = Field(..., min_length=1)

class MenuUpdate(MenuBase):
    # PATCH 用：全フィールド任意
    pass

class PortalMenu(MenuBase):
    id: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class PortalMenuList(BaseModel):
    items: List[PortalMenu]
    next_cursor: Optional[str] = None


@router.get("/portal/menu", summary="メニュー一覧", response_model=PortalMenuList)
def list_menus(
    menu_xml_id: Optional[str] = Query(None),
    action_type: Optional[ActionType] = Query(None),
    target_model: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None, description='Base64({"last_id":<int>})'),
):
    """
    Keyset ページング想定（cursor = Base64({"last_id": <int>})）。
    いまはモックで空返却。Repo接続時にDB検索へ差し替え。
    """
    return {"items": [], "next_cursor": None}


@router.post(
    "/portal/menu",
    summary="作成",
    status_code=status.HTTP_201_CREATED,
    response_model=PortalMenu,
)
def create_menu(payload: MenuCreate = Body(...)):
    """
    モック実装：受領値をそのまま整形して返却。
    後で Repo に差し替え（INSERT ... RETURNING）。
    """
    return {
        "id": 1,
        **payload.model_dump(exclude_unset=True),
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


@router.patch(
    "/portal/menu/{id}",
    summary="更新",
    response_model=PortalMenu,
)
def update_menu(
    id: int = Path(..., ge=1),
    payload: MenuUpdate = Body(...),
):
    """
    モック実装：部分更新（PATCH）。実DBでは JSONB等があればシャローマージで更新。
    """
    base = {
        "id": id,
        "menu_xml_id": "sale.menu_sale_quotations",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    return {**base, **payload.model_dump(exclude_unset=True)}


@router.post(
    "/portal/menu/bulk_upsert",
    summary="複数メニューの一括UPSERT",
    response_model=Dict[str, Any],
)
def bulk_upsert_menus(payload: List[MenuCreate] = Body(...)):
    """
    モック実装：件数のみ返却。
    実装時は menu_xml_id を一意キーとして ON CONFLICT DO UPDATE。
    """
    return {"updated": {"portal_menu": len(payload)}, "skipped": 0}
