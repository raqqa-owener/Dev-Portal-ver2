#app/repos/portal_view_common_repo.py
from __future__ import annotations
from typing import Optional, Tuple, List, Dict, Any, Iterable
import sqlalchemy as sa
from sqlalchemy import Table, MetaData, select, bindparam  # ← bindparam を追加
from sqlalchemy.orm import Session
from sqlalchemy.engine import Connection

from app.repos.base_core import BaseCoreRepo
from app.repos.pg_helpers import upsert_one, build_update_assignments
from app.repos.errors import NotFound
from app.utils.normalization import normalize_model_name
from app.utils.view_types import to_store_order

JSONB_COLS = ("help_i18n_html", "ai_purpose_i18n", "display_fields", "default_filters", "context", "domain")


class PortalViewCommonRepo(BaseCoreRepo):
    TABLE = "portal_view_common"
    SCHEMA = "public"  # 必要なら
    """
    Unified repo:
      - If constructed with Session: full CRUD/UPSERT (BaseCoreRepo features enabled)
      - If constructed with Connection: lightweight readers (list_by_action_xmlids only)
    """
    def __init__(self, session_or_conn: Session | Connection):
        """
        - Session を受けたらそのまま BaseCoreRepo へ
        - Connection を受けたら一時 Session を組んで BaseCoreRepo へ
        どちらの経路でも `super().__init__` を必ず呼ぶ。
        """
        if isinstance(session_or_conn, Session):
            super().__init__(session_or_conn)     # TABLE/SCHEMA を使って遅延リフレクト
            self.conn = session_or_conn.connection()
        else:
            # Connection から一時的な Session を生成（トランザクション管理は呼び出し側の Connection に依存）
            tmp_sess = Session(bind=session_or_conn)
            super().__init__(tmp_sess)
            self.conn = session_or_conn

    # ---------- BaseCoreRepo 経路（Session 必須）のAPI ----------
    def create_common(self, values: Dict[str, Any]) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("create_common requires Session-backed construction")
        vals = dict(values)
        if "model" in vals:
            vals["model_tech"] = normalize_model_name(vals.pop("model"))
        row = self.create(vals)
        row["model"] = row.pop("model_tech", None)
        return row

    def list(
        self,
        *,
        action_xmlid: Optional[str],
        model: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> Tuple[List[dict], Optional[str]]:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("list requires Session-backed construction")
        eq = {}
        if action_xmlid:
            eq["action_xmlid"] = action_xmlid
        if model:
            eq["model_tech"] = normalize_model_name(model)
        return self.list_keyset(limit=limit, cursor=cursor, eq_filters=eq)

    def get_detail(self, id: int) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("get_detail requires Session-backed construction")
        row = self.get(id)
        row["model"] = row.pop("model_tech", None)
        return row

    def get_by_action_xmlid(self, axid: str) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("get_by_action_xmlid requires Session-backed construction")
        row = self.sess.execute(select(self.t).where(self.t.c.action_xmlid == axid)).mappings().first()
        if not row:
            raise NotFound(f"portal_view_common action_xmlid={axid} not found")
        return dict(row)

    def patch_common(self, id: int, values: Dict[str, Any]) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("patch_common requires Session-backed construction")
        vals = dict(values)
        if "model" in vals:
            vals["model_tech"] = normalize_model_name(vals.pop("model"))
        set_map, params = build_update_assignments(self.t, vals, jsonb_cols=JSONB_COLS)  # type: ignore[arg-type]
        row = self.update_by_id(id, set_map, params)
        row["model"] = row.pop("model_tech", None)
        return row

    def upsert(self, values: Dict[str, Any]) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("upsert requires Session-backed construction")
        vals = dict(values)
        if "model" in vals:
            vals["model_tech"] = normalize_model_name(vals.pop("model"))
        row = upsert_one(
            self.sess,
            table=self.t,  # type: ignore[arg-type]
            values=vals,
            conflict_cols=["action_xmlid"],
            returning=[
                self.t.c.id,  # type: ignore[attr-defined]
                self.t.c.action_xmlid,
                self.t.c.action_name,
                self.t.c.model_tech,
                self.t.c.model_table,
                self.t.c.view_types,
                self.t.c.primary_view_type,
                self.t.c.help_ja_text,
                self.t.c.help_en_text,
                self.t.c.ai_purpose,
                self.t.c.ai_purpose_i18n,
                self.t.c.created_at,
                self.t.c.updated_at,
            ],
        )
        m = dict(row)
        m["model"] = m.pop("model_tech", None)
        return m

    # IR 連携（Session 経路）
    def upsert_from_ir(self, ir_row: Dict[str, Any]) -> dict:
        if getattr(self, "sess", None) is None or getattr(self, "t", None) is None:
            raise RuntimeError("upsert_from_ir requires Session-backed construction")
        # view_types: IR 順で保存、primary は先頭
        vt_store = to_store_order(ir_row.get("view_types") or ir_row.get("view_mode") or [])
        payload = {
            "action_xmlid": ir_row.get("action_xmlid"),
            "action_name": ir_row.get("action_name"),
            "model": ir_row.get("model_tech"),  # API->DB で model_tech へ
            "model_table": ir_row.get("model_table"),
            "view_types": vt_store,
            "primary_view_type": vt_store[0] if vt_store else None,
            "help_ja_html": ir_row.get("help_ja_html"),
            "help_ja_text": ir_row.get("help_ja_text"),
            "help_en_html": ir_row.get("help_en_html"),
            "help_en_text": ir_row.get("help_en_text"),
            "help_i18n_html": ir_row.get("help_i18n_html"),
            "context": ir_row.get("context"),
            "domain": ir_row.get("domain"),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return self.upsert(payload)

    def ensure_by_action_xmlid(self, axid: str) -> dict:
        # 既存の get_by_action_xmlid を流用（Session 経路のみ）
        return self.get_by_action_xmlid(axid)

    # ---------- 軽量クエリ（Connection/Session どちらでも使用可） ----------
    def list_by_action_xmlids(self, action_xmlids: Iterable[str]) -> List[Dict[str, Any]]:
        ids = [x.strip().lower() for x in action_xmlids]
        if not ids:
            return []
        sql = sa.text(
            """
            SELECT id,
                   action_xmlid,
                   model_tech AS model,
                   model_table,
                   view_types,
                   primary_view_type,
                   ai_purpose,
                   ai_purpose_i18n,
                   help_ja_text,
                   help_en_text,
                   display_fields,
                   sort_field, sort_dir, default_filters
              FROM public.portal_view_common
             WHERE lower(action_xmlid) IN :ids
             ORDER BY action_xmlid
            """
        ).bindparams(bindparam("ids", expanding=True))
        return list(self.conn.execute(sql, {"ids": ids}).mappings())

    # 追加：batch_lookup_by_action_xmlids（辞書返却, action_xmlid→row）
    def batch_lookup_by_action_xmlids(self, action_xmlids: Iterable[str]) -> Dict[str, dict]:
        """
        action_xmlid の配列を受け取り、キーに action_xmlid を持つ辞書で返却。
        返却カラムは軽量参照用（common_idやupdated_atの文字列化など）に最適化。
        """
        ids = [x.strip() for x in action_xmlids if x and x.strip()]
        if not ids:
            return {}
        sql = sa.text(
            """
            SELECT
                id AS common_id,
                action_xmlid,
                action_name,
                model_tech,
                model_table,
                view_types,
                primary_view_type,
                ai_purpose,
                help_ja_text,
                to_char(updated_at, 'YYYY-MM-DD"T"HH24:MI:SSOF') AS updated_at
            FROM public.portal_view_common
            WHERE action_xmlid IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True))
        rows = self.conn.execute(sql, {"ids": ids}).mappings().all()
        out: Dict[str, dict] = {}
        for r in rows:
            # ★ キーを小文字・trimで正規化
            k = (r["action_xmlid"] or "").strip().lower()
            out[k] = dict(r)
        return out
