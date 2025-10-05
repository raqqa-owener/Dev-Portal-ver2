from typing import Optional, List, Dict, Any, Tuple
import base64, json
from sqlalchemy import text
from sqlalchemy.orm import Session

def _enc_cursor(last_table: str, last_field: str) -> str:
    raw = json.dumps([last_table or "", last_field or ""]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _dec_cursor(cur: Optional[str]) -> tuple[str, str]:
    if not cur:
        return ("", "")
    s = cur + "=" * (-len(cur) % 4)
    t, f = json.loads(base64.urlsafe_b64decode(s.encode()).decode())
    return (t or "", f or "")

class IRFieldSrcRepo:
    """
    public.ir_field_src 読み取り専用
    カラム:
      model, model_table, field_name, ttype, label_en_us, label_ja_jp, label_i18n,
      code_status, notes, origin, show_invisible, pk_columns, is_pk
    """

    def __init__(self, sess: Session):
        self.sess = sess

    def count(self) -> int:
        return self.sess.execute(text("SELECT COUNT(*) FROM public.ir_field_src")).scalar_one()

    def list_offset(self, *, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        sql = """
        SELECT model, model_table, field_name, ttype, label_en_us, label_ja_jp, label_i18n,
               code_status, notes, origin, show_invisible, pk_columns, is_pk
          FROM public.ir_field_src
         ORDER BY model_table ASC, field_name ASC
         LIMIT :limit OFFSET :offset
        """
        rows = self.sess.execute(text(sql), {"limit": limit, "offset": offset}).mappings().all()
        return [dict(r) for r in rows]

    def list_keyset(
        self, *, limit: int = 200, cursor: Optional[str] = None, search: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        lt, lf = _dec_cursor(cursor)
        base = """
        SELECT model, model_table, field_name, ttype, label_en_us, label_ja_jp, label_i18n,
               code_status, notes, origin, show_invisible, pk_columns, is_pk
          FROM public.ir_field_src
         WHERE (model_table, field_name) > (:lt, :lf)
        """
        params: Dict[str, Any] = {"lt": lt, "lf": lf}
        if search:
            base += " AND (model ILIKE :q OR model_table ILIKE :q OR field_name ILIKE :q OR label_en_us ILIKE :q)"
            params["q"] = f"%{search}%"
        base += " ORDER BY model_table ASC, field_name ASC LIMIT :limit"
        params["limit"] = limit

        items = [dict(r) for r in self.sess.execute(text(base), params).mappings().all()]
        next_cur = _enc_cursor(items[-1]["model_table"], items[-1]["field_name"]) if items else None
        return items, next_cur
