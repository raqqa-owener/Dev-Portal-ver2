from typing import Optional, List, Dict, Any, Tuple
import base64, json
from sqlalchemy import text
from sqlalchemy.orm import Session

def _enc_cursor(last_table: str, last_model: str) -> str:
    raw = json.dumps([last_table or "", last_model or ""]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _dec_cursor(cur: Optional[str]) -> tuple[str, str]:
    if not cur:
        return ("", "")
    s = cur + "=" * (-len(cur) % 4)
    t, m = json.loads(base64.urlsafe_b64decode(s.encode()).decode())
    return (t or "", m or "")

class IRModelSrcRepo:
    """
    public.ir_model_src 読み取り専用
    カラム:
      model, model_table, label_en_us, label_ja_jp, label_i18n, notes, created_at, updated_at
    """

    def __init__(self, sess: Session):
        self.sess = sess

    def count(self) -> int:
        return self.sess.execute(text("SELECT COUNT(*) FROM public.ir_model_src")).scalar_one()

    def list_offset(self, *, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        sql = """
        SELECT model, model_table, label_en_us, label_ja_jp, label_i18n, notes, created_at, updated_at
          FROM public.ir_model_src
         ORDER BY model_table ASC, model ASC
         LIMIT :limit OFFSET :offset
        """
        rows = self.sess.execute(text(sql), {"limit": limit, "offset": offset}).mappings().all()
        return [dict(r) for r in rows]

    def list_keyset(
        self, *, limit: int = 200, cursor: Optional[str] = None, search: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        lt, lm = _dec_cursor(cursor)
        base = """
        SELECT model, model_table, label_en_us, label_ja_jp, label_i18n, notes, created_at, updated_at
          FROM public.ir_model_src
         WHERE (model_table, model) > (:lt, :lm)
        """
        params: Dict[str, Any] = {"lt": lt, "lm": lm}

        if search:
            base += """
              AND (
                    model ILIKE :q
                 OR model_table ILIKE :q
                 OR COALESCE(label_en_us,'') ILIKE :q
                 OR COALESCE(label_ja_jp,'') ILIKE :q
              )
            """
            params["q"] = f"%{search}%"

        base += " ORDER BY model_table ASC, model ASC LIMIT :limit"
        params["limit"] = limit

        items = [dict(r) for r in self.sess.execute(text(base), params).mappings().all()]
        next_cur = _enc_cursor(items[-1]["model_table"], items[-1]["model"]) if items else None
        return items, next_cur
