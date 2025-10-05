from typing import Optional, List, Dict, Any, Tuple
import base64, json
from sqlalchemy import text
from sqlalchemy.orm import Session

def _enc_cursor(last_table: str, last_axid: str, last_aid: int) -> str:
    raw = json.dumps([last_table or "", last_axid or "", int(last_aid or 0)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _dec_cursor(cur: Optional[str]) -> tuple[str, str, int]:
    if not cur:
        return ("", "", 0)
    s = cur + "=" * (-len(cur) % 4)
    t, x, i = json.loads(base64.urlsafe_b64decode(s.encode()).decode())
    return (t or "", x or "", int(i or 0))

class IRViewSrcRepo:
    """
    public.ir_view_src 読み取り専用（action-centric）
    カラム:
      action_xmlid, action_id, action_name, model_label, model_tech, model_table,
      view_types, primary_view_type, help_i18n_html, help_ja_html, help_ja_text,
      help_en_html, help_en_text, view_mode, context, domain
    """

    def __init__(self, sess: Session):
        self.sess = sess

    def count(self) -> int:
        return self.sess.execute(text("SELECT COUNT(*) FROM public.ir_view_src")).scalar_one()

    def list_offset(self, *, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        sql = """
        SELECT action_xmlid, action_id, action_name, model_label, model_tech, model_table,
               view_types, primary_view_type, help_i18n_html, help_ja_html, help_ja_text,
               help_en_html, help_en_text, view_mode, context, domain
          FROM public.ir_view_src
         ORDER BY model_table ASC, COALESCE(action_xmlid,'' ) ASC, COALESCE(action_id,0) ASC
         LIMIT :limit OFFSET :offset
        """
        rows = self.sess.execute(text(sql), {"limit": limit, "offset": offset}).mappings().all()
        return [dict(r) for r in rows]

    def list_keyset(
        self, *, limit: int = 200, cursor: Optional[str] = None, search: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        lt, lx, lid = _dec_cursor(cursor)
        base = """
        SELECT action_xmlid, action_id, action_name, model_label, model_tech, model_table,
               view_types, primary_view_type, help_i18n_html, help_ja_html, help_ja_text,
               help_en_html, help_en_text, view_mode, context, domain
          FROM public.ir_view_src
         WHERE (model_table, COALESCE(action_xmlid,''), COALESCE(action_id,0)) >
               (:lt, :lx, CAST(:lid AS bigint))
        """
        params: Dict[str, Any] = {"lt": lt, "lx": lx, "lid": int(lid)}
        if search:
            base += " AND (action_xmlid ILIKE :q OR action_name ILIKE :q OR model_label ILIKE :q OR model_tech ILIKE :q OR model_table ILIKE :q)"
            params["q"] = f"%{search}%"
        base += " ORDER BY model_table ASC, COALESCE(action_xmlid,'') ASC, COALESCE(action_id,0) ASC LIMIT :limit"
        params["limit"] = limit

        items = [dict(r) for r in self.sess.execute(text(base), params).mappings().all()]
        if items:
            last = items[-1]
            next_cur = _enc_cursor(last["model_table"], last.get("action_xmlid") or "", last.get("action_id") or 0)
        else:
            next_cur = None
        return items, next_cur
