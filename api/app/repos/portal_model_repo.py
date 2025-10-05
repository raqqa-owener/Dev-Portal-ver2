from typing import Optional, Tuple, List, Dict, Any
from sqlalchemy import Table, MetaData, select, or_
from sqlalchemy.orm import Session
from sqlalchemy.engine import Connection   # ★ これを追加
from app.repos.base_core import BaseCoreRepo
from app.repos.pg_helpers import upsert_one
from app.repos.errors import NotFound
from app.utils.normalization import normalize_model_name, merge_label_i18n


class PortalModelRepo(BaseCoreRepo):
    TABLE = "portal_model"
    SCHEMA = "public"

    def __init__(self, session_or_conn: Session | Connection):
        if isinstance(session_or_conn, Session):
            super().__init__(session_or_conn)
            self.conn = session_or_conn.connection()
        else:
            tmp_sess = Session(bind=session_or_conn)
            super().__init__(tmp_sess)
            self.conn = session_or_conn


    def list(self, *, q: Optional[str], limit: int, cursor: Optional[str]) -> Tuple[List[dict], Optional[str]]:
        last_id = 0
        from app.utils.cursor import decode_last_id_cursor, encode_last_id_cursor
        last_id = decode_last_id_cursor(cursor)
        stmt = select(self.t).where(self.t.c.id > last_id).order_by(self.t.c.id.asc()).limit(limit)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(self.t.c.model.ilike(like), self.t.c.model_table.ilike(like)))
        rows = self.sess.execute(stmt).mappings().all()
        items = [dict(r) for r in rows]
        next_cursor = encode_last_id_cursor(items[-1]["id"]) if items else None
        return items, next_cursor

    def get_by_model(self, model: str) -> dict:
        model_n = normalize_model_name(model)
        row = self.sess.execute(select(self.t).where(self.t.c.model == model_n)).mappings().first()
        if not row:
            raise NotFound(f"portal_model model={model_n} not found")
        return dict(row)

    def create_model(self, values: Dict[str, Any]) -> dict:
        if "model" in values:
            values = dict(values)
            values["model"] = normalize_model_name(values["model"])  
        return self.create(values)

    def patch_model(self, id: int, values: Dict[str, Any]) -> dict:
        if "model" in values:
            values = dict(values)
            values["model"] = normalize_model_name(values["model"])  
        return self.update_by_id(id, values)

    def upsert(self, values: Dict[str, Any]) -> dict:
        vals = dict(values)
        if "model" in vals:
            vals["model"] = normalize_model_name(vals["model"])  
        row = upsert_one(
            self.sess,
            table=self.t,
            values=vals,
            conflict_cols=["model"],
            returning=[self.t.c.id, self.t.c.model, self.t.c.model_table, self.t.c.label_i18n, self.t.c.notes, self.t.c.created_at, self.t.c.updated_at],
        )
        return dict(row)

    # IR 連携
    def upsert_from_ir(self, ir_row: Dict[str, Any]) -> dict:
        model = normalize_model_name(ir_row.get("model"))
        values = {
            "model": model,
            "model_table": ir_row.get("model_table"),
            "label_i18n": merge_label_i18n(ir_row.get("label_i18n"), ir_row.get("label_ja_jp"), ir_row.get("label_en_us")),
            "notes": ir_row.get("notes"),
        }
        # null 無視
        values = {k: v for k, v in values.items() if v is not None}
        return self.upsert(values)

    def scaffold_if_missing(self, *, model: str, model_table: str, label_i18n: Optional[Dict[str, str]] = None, notes: Optional[str] = None) -> dict:
        model_n = normalize_model_name(model)
        try:
            return self.get_by_model(model_n)
        except NotFound:
            pass
        values = {"model": model_n, "model_table": model_table}
        if label_i18n is not None:
            values["label_i18n"] = label_i18n
        if notes is not None:
            values["notes"] = notes
        return self.create(values)