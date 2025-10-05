from typing import Dict, Any, List
from sqlalchemy.orm import Session
import sqlalchemy as sa

from app.schemas.extract_field import ExtractFieldRequest
from app.schemas.extract_view_common import ExtractViewCommonRequest
from app.schemas.common import ExtractResult, ExtractResultDetail
from app.utils.normalization import normalize_label, normalize_longtext
from app.utils.natural_key import build_field_key, build_view_common_key
from app.utils.text_hash import sha256_text
from app.repos.portal_translate_repo import PortalTranslateRepo
from app.repos.portal_field_repo import PortalFieldRepo
from app.repos.portal_view_common_repo import PortalViewCommonRepo


SRC_LANG = 'ja_JP'
TGT_LANG = 'en_US'


def _has_en_in_label(label_i18n: Dict[str, Any] | None) -> bool:
    if not label_i18n:
        return False
    for k in ('en', 'en_US', 'en-us'):
        v = label_i18n.get(k)
        if isinstance(v, str) and v.strip():
            return True
    return False


def extract_field(req: ExtractFieldRequest, session: Session) -> ExtractResult:
    conn = session.connection()
    f_repo = PortalFieldRepo(conn)
    t_repo = PortalTranslateRepo(conn)

    # pick candidates
    if req.models and req.fields:
        rows = f_repo.list_by_models_and_field_names(req.models, req.fields)
    elif req.models:
        rows = f_repo.list_by_models(req.models)
    else:
        rows = f_repo.list_by_field_names(req.fields or [])

    result = ExtractResult()

    for r in rows:
        model = (r['model'] or '').strip()
        field = (r['field_name'] or '').strip()
        label_i18n = r.get('label_i18n') or {}
        notes = r.get('notes') or ''

        # EN already?
        if _has_en_in_label(label_i18n):
            result.skipped_has_en += 1
            result.details.append(ExtractResultDetail(natural_key=build_field_key(model, field), reason='skipped_has_en'))
            continue

        label_ja = label_i18n.get('ja') or label_i18n.get('ja_JP') or ''
        norm_label = normalize_label(label_ja)
        norm_notes = normalize_longtext(notes)

        if not norm_label and not norm_notes:
            result.skipped_no_ja += 1
            result.details.append(ExtractResultDetail(natural_key=build_field_key(model, field), reason='skipped_no_ja'))
            continue

        nk = build_field_key(model, field)
        src_text = (norm_label or '') + ("\n\n" + norm_notes if norm_notes else '')
        src_hash = sha256_text(src_text)

        outcome = t_repo.upsert_source(
            entity='field',
            natural_key=nk,
            src_lang=SRC_LANG,
            tgt_lang=TGT_LANG,
            source_text=src_text,
            source_hash=src_hash,
            mode=req.mode,
        )
        result.picked += 1
        if outcome == 'inserted':
            result.inserted += 1
        elif outcome == 'updated':
            result.updated += 1
        elif outcome in ('skipped_no_change', 'skipped_existing'):
            # map both to skipped_no_change for counters except details retain reason
            result.skipped_no_change += 1
        result.details.append(ExtractResultDetail(natural_key=nk, reason=outcome))

    return result


def _has_en_for_view_ai_purpose(row: Dict[str, Any]) -> bool:
    i18n = row.get('ai_purpose_i18n') or {}
    if isinstance(i18n, dict):
        for k in ('en', 'en_US', 'en-us'):
            v = i18n.get(k)
            if isinstance(v, str) and v.strip():
                return True
    return False


def extract_view_common(req: ExtractViewCommonRequest, session: Session) -> ExtractResult:
    conn = session.connection()
    v_repo = PortalViewCommonRepo(conn)
    t_repo = PortalTranslateRepo(conn)

    rows = v_repo.list_by_action_xmlids(req.action_xmlids)

    # map by action for quick lookup
    found = {r['action_xmlid'].lower(): r for r in rows}

    result = ExtractResult()

    for axid in [x.strip().lower() for x in req.action_xmlids]:
        row = found.get(axid)
        if not row:
            # mark both (or selected targets) as not found
            for tgt in req.targets or ['ai_purpose', 'help']:
                nk = build_view_common_key(axid, tgt)  # will validate axid format
                result.skipped_not_found += 1
                result.details.append(ExtractResultDetail(natural_key=nk, reason='skipped_not_found'))
            continue

        for tgt in req.targets or ['ai_purpose', 'help']:
            if tgt == 'ai_purpose':
                ja = row.get('ai_purpose') or ''
                en_exists = _has_en_for_view_ai_purpose(row)
                norm = normalize_longtext(ja)  # plain text
            else:  # help
                ja = row.get('help_ja_text') or ''
                en_exists = bool((row.get('help_en_text') or '').strip())
                norm = normalize_longtext(ja)

            nk = build_view_common_key(row['action_xmlid'], tgt)

            if en_exists:
                result.skipped_has_en += 1
                result.details.append(ExtractResultDetail(natural_key=nk, reason='skipped_has_en'))
                continue

            if not norm:
                result.skipped_no_ja += 1
                result.details.append(ExtractResultDetail(natural_key=nk, reason='skipped_no_ja'))
                continue

            src_text = norm
            src_hash = sha256_text(src_text)

            outcome = t_repo.upsert_source(
                entity='view_common',
                natural_key=nk,
                src_lang=SRC_LANG,
                tgt_lang=TGT_LANG,
                source_text=src_text,
                source_hash=src_hash,
                mode=req.mode,
            )
            result.picked += 1
            if outcome == 'inserted':
                result.inserted += 1
            elif outcome == 'updated':
                result.updated += 1
            elif outcome in ('skipped_no_change', 'skipped_existing'):
                result.skipped_no_change += 1
            result.details.append(ExtractResultDetail(natural_key=nk, reason=outcome))

    return result