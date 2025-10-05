# Orchestration for extract
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple
from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session
import hashlib
import re

# ---- helpers -----------------------------------------------------

SRC_LANG = "ja_JP"
TGT_LANG = "en_US"

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

_ws_re = re.compile(r"[ \t\f\v]+")
_nl_re = re.compile(r"\s*\n\s*")

def _normalize_plain(s: Optional[str]) -> str:
    if not s:
        return ""
    # 改行を正規化し、空白をつめる（日本語は詰めすぎない程度）
    s = s.replace("\r\n", "\n").replace("\r", "\n").strip()
    s = _nl_re.sub("\n", s)
    s = _ws_re.sub(" ", s)
    return s.strip()

def _label_ja(label_i18n: Optional[Dict]) -> str:
    if not isinstance(label_i18n, dict):
        return ""
    for k in ("ja", "ja_JP"):
        v = label_i18n.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _has_en(label_i18n: Optional[Dict], extra: Optional[str] = None) -> bool:
    # ENラベル or ENテキストが存在するなら抽出対象外
    if isinstance(label_i18n, dict):
        for k in ("en", "en_US"):
            v = label_i18n.get(k)
            if isinstance(v, str) and v.strip():
                return True
    if isinstance(extra, str) and extra.strip():
        return True
    return False

# ---- DB fetchers -------------------------------------------------

def _fetch_fields(session: Session, models: Optional[List[str]], fields: Optional[List[str]]):
    clauses = []
    params = {}

    if models:
        clauses.append("lower(model) IN :models")
        params["models"] = [m.lower() for m in models]
    if fields:
        clauses.append("lower(field_name) IN :fns")
        params["fns"] = [f.lower() for f in fields]

    where = " AND ".join(clauses) if clauses else "TRUE"

    sql = text(f"""
        SELECT id, model, model_table, field_name, ttype, label_i18n, notes
          FROM public.portal_fields
         WHERE {where}
         ORDER BY model, field_name
    """)
    # expanding bind 付与（存在するもののみ）
    bps = []
    if "models" in params:
        bps.append(bindparam("models", expanding=True))
    if "fns" in params:
        bps.append(bindparam("fns", expanding=True))
    if bps:
        sql = sql.bindparams(*bps)

    return list(session.execute(sql, params).mappings())

def _fetch_view_commons(session: Session, action_xmlids: List[str]):
    sql = text("""
        SELECT id,
               action_xmlid,
               model_tech  AS model,
               model_table,
               ai_purpose,
               ai_purpose_i18n,
               help_ja_text,
               help_en_text
          FROM public.portal_view_common
         WHERE lower(action_xmlid) IN :ids
         ORDER BY action_xmlid
    """).bindparams(bindparam("ids", expanding=True))
    return list(session.execute(sql, {"ids": [x.lower() for x in action_xmlids]}).mappings())

# ---- UPSERT into portal_translate --------------------------------

def _get_existing(session: Session, entity: str, natural_key: str):
    row = session.execute(
        text("""
          SELECT id, source_hash, state
            FROM public.portal_translate
           WHERE entity=:e AND natural_key=:nk
             AND src_lang=:sl AND tgt_lang=:tl
        """),
        {"e": entity, "nk": natural_key, "sl": SRC_LANG, "tl": TGT_LANG},
    ).mappings().first()
    return row

def _insert_translate(session: Session, entity: str, natural_key: str,
                      model: Optional[str], model_table: Optional[str],
                      source_text: str, source_hash: str):
    session.execute(
        text("""
          INSERT INTO public.portal_translate
            (entity, natural_key, src_lang, tgt_lang,
             source_text, translated_text, source_hash, state,
             model, model_table, metadata)
          VALUES
            (:e, :nk, :sl, :tl,
             :st, NULL, :sh, 'pending',
             :model, :mtable, '{}'::jsonb)
        """),
        {
            "e": entity, "nk": natural_key, "sl": SRC_LANG, "tl": TGT_LANG,
            "st": source_text, "sh": source_hash,
            "model": model, "mtable": model_table,
        },
    )

def _update_translate_if_changed(session: Session, row_id: int,
                                 source_text: str, source_hash: str):
    session.execute(
        text("""
          UPDATE public.portal_translate
             SET source_text = :st,
                 source_hash = :sh,
                 translated_text = NULL,
                 last_error = NULL,
                 state = 'pending',
                 updated_at = now()
           WHERE id = :id
        """),
        {"st": source_text, "sh": source_hash, "id": row_id},
    )

# ---- Public API: field -------------------------------------------

def extract_field(payload, session: Session) -> Dict:
    """
    payload: ExtractFieldRequest
    return: ExtractResult dict
    """
    models = payload.models or None
    fields = payload.fields or None
    mode   = payload.mode or "upsert_if_changed"

    res = {
        "picked": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_no_ja": 0,
        "skipped_has_en": 0,
        "skipped_not_found": 0,
        "details": [],
    }

    rows = _fetch_fields(session, models, fields)
    if not rows:
        return res

    for r in rows:
        model       = r["model"]
        model_table = r["model_table"]
        field_name  = r["field_name"]
        label_i18n  = r["label_i18n"]
        notes       = r["notes"]

        # JAテキスト抽出
        ja_label = _label_ja(label_i18n)
        ja_notes = _normalize_plain(notes)
        src_text = _normalize_plain(ja_label)
        if ja_notes:
            src_text = (src_text + "\n\n" + ja_notes).strip()

        # フィルタ
        if not src_text:
            res["skipped_no_ja"] += 1
            res["details"].append({"natural_key": f"field::{model}::{field_name}", "reason": "no_ja"})
            continue
        if _has_en(label_i18n):
            res["skipped_has_en"] += 1
            res["details"].append({"natural_key": f"field::{model}::{field_name}", "reason": "has_en"})
            continue

        res["picked"] += 1
        nk = f"field::{model}::{field_name}"
        sh = _sha256(src_text)

        existing = _get_existing(session, "field", nk)
        if existing:
            if mode == "skip_existing":
                res["details"].append({"natural_key": nk, "reason": "exists_skip"})
                continue
            if existing["source_hash"] == sh:
                res["details"].append({"natural_key": nk, "reason": "no_change"})
                # 仕様上は skipped_no_change を設けていないので details のみ
                continue
            _update_translate_if_changed(session, existing["id"], src_text, sh)
            res["updated"] += 1
        else:
            if mode == "upsert" or mode == "upsert_if_changed" or mode is None:
                _insert_translate(session, "field", nk, model, model_table, src_text, sh)
                res["inserted"] += 1
            else:
                res["details"].append({"natural_key": nk, "reason": f"mode={mode}_skip"})

    return res

# ---- Public API: view_common -------------------------------------

def extract_view_common(payload, session: Session) -> Dict:
    """
    payload: ExtractViewCommonRequest
    return: ExtractResult dict
    """
    action_xmlids = payload.action_xmlids or []
    targets = payload.targets or ["ai_purpose", "help"]
    mode    = payload.mode or "upsert_if_changed"

    res = {
        "picked": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_no_ja": 0,
        "skipped_has_en": 0,
        "skipped_not_found": 0,
        "details": [],
    }
    if not action_xmlids:
        return res

    rows = _fetch_view_commons(session, action_xmlids)
    if not rows:
        # 与えられた action_xmlids 全部が見つからないケース
        for x in action_xmlids:
            res["skipped_not_found"] += 1
            res["details"].append({"natural_key": f"view_common::{x}::*", "reason": "not_found"})
        return res

    rows_by_xmlid = {r["action_xmlid"]: r for r in rows}
    for xmlid in action_xmlids:
        row = rows_by_xmlid.get(xmlid.lower()) or rows_by_xmlid.get(xmlid)
        if not row:
            res["skipped_not_found"] += 1
            res["details"].append({"natural_key": f"view_common::{xmlid}::*", "reason": "not_found"})
            continue

        model       = row["model"]
        model_table = row["model_table"]
        # ai_purpose
        if "ai_purpose" in targets:
            ja_src = _normalize_plain(row.get("ai_purpose") or
                                      (row.get("ai_purpose_i18n") or {}).get("ja") or
                                      (row.get("ai_purpose_i18n") or {}).get("ja_JP"))
            has_en = _has_en(row.get("ai_purpose_i18n"))
            nk = f"view_common::{row['action_xmlid']}::ai_purpose"
            if not ja_src:
                res["skipped_no_ja"] += 1
                res["details"].append({"natural_key": nk, "reason": "no_ja"})
            elif has_en:
                res["skipped_has_en"] += 1
                res["details"].append({"natural_key": nk, "reason": "has_en"})
            else:
                res["picked"] += 1
                sh = _sha256(ja_src)
                existing = _get_existing(session, "view_common", nk)
                if existing:
                    if mode == "skip_existing":
                        res["details"].append({"natural_key": nk, "reason": "exists_skip"})
                    elif existing["source_hash"] == sh:
                        res["details"].append({"natural_key": nk, "reason": "no_change"})
                    else:
                        _update_translate_if_changed(session, existing["id"], ja_src, sh)
                        res["updated"] += 1
                else:
                    _insert_translate(session, "view_common", nk, model, model_table, ja_src, sh)
                    res["inserted"] += 1

        # help
        if "help" in targets:
            ja_src = _normalize_plain(row.get("help_ja_text"))
            has_en = _has_en(None, row.get("help_en_text"))
            nk = f"view_common::{row['action_xmlid']}::help"
            if not ja_src:
                res["skipped_no_ja"] += 1
                res["details"].append({"natural_key": nk, "reason": "no_ja"})
            elif has_en:
                res["skipped_has_en"] += 1
                res["details"].append({"natural_key": nk, "reason": "has_en"})
            else:
                res["picked"] += 1
                sh = _sha256(ja_src)
                existing = _get_existing(session, "view_common", nk)
                if existing:
                    if mode == "skip_existing":
                        res["details"].append({"natural_key": nk, "reason": "exists_skip"})
                    elif existing["source_hash"] == sh:
                        res["details"].append({"natural_key": nk, "reason": "no_change"})
                    else:
                        _update_translate_if_changed(session, existing["id"], ja_src, sh)
                        res["updated"] += 1
                else:
                    _insert_translate(session, "view_common", nk, model, model_table, ja_src, sh)
                    res["inserted"] += 1

    return res
