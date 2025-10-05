from __future__ import annotations
from typing import Dict
from sqlalchemy import Table, MetaData, select
from sqlalchemy.orm import Session
from sqlalchemy.engine import Connection   # ★ これを追加
from app.repos.base_core import BaseCoreRepo
from app.repos.pg_helpers import upsert_one
from app.repos.errors import NotFound


class PortalViewRepo(BaseCoreRepo):
    TABLE = "portal_view"
    SCHEMA = "public"

    def __init__(self, session_or_conn: Session | Connection):
        if isinstance(session_or_conn, Session):
            super().__init__(session_or_conn)
            self.conn = session_or_conn.connection()
        else:
            tmp_sess = Session(bind=session_or_conn)
            super().__init__(tmp_sess)
            self.conn = session_or_conn

    def get_by_common_and_type(self, *, common_id: int, view_type: str) -> dict:
        row = self.sess.execute(
            select(self.t).where((self.t.c.common_id == common_id) & (self.t.c.view_type == view_type))
        ).mappings().first()
        if not row:
            raise NotFound(f"portal_view common_id={common_id} view_type={view_type} not found")
        return dict(row)

    def upsert_skeleton(self, *, common_id: int, view_type: str, model: str, enabled: bool = True, is_primary: bool = False) -> dict:
        vals: Dict[str, object] = {
            "common_id": common_id,
            "view_type": view_type,
            "model": model,
            "enabled": enabled,
            "is_primary": is_primary,
        }
        row = upsert_one(
            self.sess,
            table=self.t,
            values=vals,
            conflict_cols=["common_id", "view_type"],
            returning=[self.t.c.id, self.t.c.common_id, self.t.c.view_type, self.t.c.model, self.t.c.enabled, self.t.c.is_primary, self.t.c.created_at, self.t.c.updated_at],
        )
        return dict(row)

    def set_primary_by_view_id(self, *, view_id: int) -> dict:
        row = self.update_by_id(view_id, {"is_primary": True})
        return row