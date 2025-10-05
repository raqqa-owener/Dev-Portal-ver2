# Translation worker (pending -> translated)
# -*- coding: utf-8 -*-
from typing import Dict, List, Optional
import time

from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session

from app import config

# ---------- providers ----------

class Translator:
    def translate(self, texts: List[str], src: str, tgt: str) -> List[str]:
        raise NotImplementedError

class DummyTranslator(Translator):
    def translate(self, texts: List[str], src: str, tgt: str) -> List[str]:
        # 開発用：原文の先頭に (EN) を付与
        return [f"(EN){t}" for t in texts]

class OpenAITranslator(Translator):
    def __init__(self):
        from openai import OpenAI
        kwargs = {}
        if config.OPENAI_BASE_URL:
            kwargs["base_url"] = config.OPENAI_BASE_URL
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set")
        kwargs["api_key"] = config.OPENAI_API_KEY
        self.client = OpenAI(**kwargs)

    def translate(self, texts: List[str], src: str, tgt: str) -> List[str]:
        out: List[str] = []
        for t in texts:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a professional software localization translator. "
                        "Translate the user's Japanese UI label/help text into clear, concise English. "
                        "Do not add explanations. Preserve placeholders like {name} or %(count)s. "
                        "Return English only."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Source language: {src}\nTarget language: {tgt}\nText:\n{t}",
                },
            ]
            resp = self.client.chat.completions.create(
                model=config.OPENAI_MODEL,
                temperature=0.2,
                messages=messages,
            )
            content = (resp.choices[0].message.content or "").strip()
            out.append(content)
            # RateLimit 緩和
            time.sleep(0.05)
        return out


# provider インスタンスはキャッシュ（毎回 OpenAIClient を作らない）
_PROVIDER: Optional[Translator] = None
def _get_provider() -> Translator:
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    if config.TRANSLATE_PROVIDER == "openai":
        _PROVIDER = OpenAITranslator()
    else:
        _PROVIDER = DummyTranslator()
    return _PROVIDER


# ---------- helpers ----------

SRC_LANG = config.TRANSLATE_SRC_LANG
TGT_LANG = config.TRANSLATE_TGT_LANG

def _trim(text: Optional[str], limit: int = 2000) -> str:
    if not text:
        return ""
    return (text[:limit] + "…") if len(text) > limit else text


# ---------- db io ----------

def _pick_pending(session: Session, limit: int, entities: Optional[List[str]], src: str, tgt: str):
    """
    pending のみ id ASC で最大 limit 件
    src/tgt 言語は payload 指定を尊重（未指定はデフォルト）
    """
    clauses = ["state='pending'", "src_lang=:sl", "tgt_lang=:tl"]
    params = {"sl": src, "tl": tgt, "limit": limit}

    sql = """
      SELECT id, entity, natural_key, model, model_table,
             source_text, source_hash
        FROM public.portal_translate
       WHERE {where}
       ORDER BY id ASC
       LIMIT :limit
    """

    if entities:
        clauses.append("entity IN :ents")
        params["ents"] = entities
        q = text(sql.format(where=" AND ".join(clauses))).bindparams(
            bindparam("ents", expanding=True)
        )
    else:
        q = text(sql.format(where=" AND ".join(clauses)))

    return list(session.execute(q, params).mappings())

def _mark_translated(session: Session, row_id: int, translated_text: str):
    session.execute(
        text(
            """
          UPDATE public.portal_translate
             SET translated_text = :tt,
                 state = 'translated',
                 last_error = NULL,
                 updated_at = now()
           WHERE id = :id
        """
        ),
        {"tt": translated_text, "id": row_id},
    )

def _mark_failed(session: Session, row_id: int, error: str):
    session.execute(
        text(
            """
          UPDATE public.portal_translate
             SET state = 'failed',
                 last_error = :err,
                 updated_at = now()
           WHERE id = :id
        """
        ),
        {"err": (error or "")[:300], "id": row_id},
    )


# ---------- public api ----------

def run_translate(payload, session: Session) -> Dict:
    """
    TranslateRunRequest -> TranslateRunResult (dict)
    """
    # payload 指定があれば優先
    src = payload.source_lang or SRC_LANG
    tgt = payload.target_lang or TGT_LANG
    limit = payload.limit or int(config.TRANSLATE_LIMIT_DEF)
    entities = payload.entities or None

    rows = _pick_pending(session, limit, entities, src, tgt)

    res: Dict = {"picked": len(rows), "translated": 0, "failed": 0, "samples": []}
    if not rows:
        return res

    provider = _get_provider()

    for r in rows:
        rid = r["id"]
        nk = r["natural_key"]
        try:
            src_text = _trim(r["source_text"])
            tt = provider.translate([src_text], src, tgt)[0]
            _mark_translated(session, rid, tt)
            res["translated"] += 1
            if len(res["samples"]) < 5:
                res["samples"].append(
                    {
                        "natural_key": nk,
                        "entity": r["entity"],
                        "model": r["model"],
                        "translated_label": tt,  # 簡易表示
                        "status": "translated",
                    }
                )
        except Exception as e:
            _mark_failed(session, rid, str(e))
            res["failed"] += 1
            if len(res["samples"]) < 5:
                res["samples"].append(
                    {
                        "natural_key": nk,
                        "entity": r["entity"],
                        "model": r["model"],
                        "status": "failed",
                    }
                )

    return res
