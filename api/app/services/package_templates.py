# Make docs for Chroma export
# doc_text を 4行テンプレで構成する関数。
# - render_field_doc(): フィールド用
# - render_view_common_doc(): 画面（共通）用

from __future__ import annotations
from typing import Dict

FIELD_TEMPLATE_LINES = (
    "【フィールド】{label_ja}（{model}.{field_name}）",
    "【データ型】{jp_datatype}（ttype={ttype}）",
    "{desc_line}",
    "【モデル】{model} / {model_table}",
)

VIEW_COMMON_TEMPLATE_LINES = (
    "【画面】{action_display}",
    "【目的】{ai_purpose_ja}",
    "【使い方】{help_ja_text}",
    "【モデル】{model_tech} / {model_table} / 主ビュー={primary_view_type}",
)

def render_field_doc(*, label_ja: str, model: str, field_name: str, model_table: str, ttype: str, jp_datatype: str, notes_ja: str | None) -> str:
    desc_line = f"【説明】{notes_ja}" if (notes_ja or "").strip() else ""
    lines = [
        FIELD_TEMPLATE_LINES[0].format(label_ja=label_ja, model=model, field_name=field_name),
        FIELD_TEMPLATE_LINES[1].format(jp_datatype=jp_datatype, ttype=ttype),
        (FIELD_TEMPLATE_LINES[2].format(desc_line=desc_line) if desc_line else ""),
        FIELD_TEMPLATE_LINES[3].format(model=model, model_table=model_table),
    ]
    return "\n".join([l for l in lines if l])

def render_view_common_doc(*, action_display: str, ai_purpose_ja: str, help_ja_text: str, model_tech: str, model_table: str, primary_view_type: str | None) -> str:
    lines = [
        VIEW_COMMON_TEMPLATE_LINES[0].format(action_display=action_display),
        VIEW_COMMON_TEMPLATE_LINES[1].format(ai_purpose_ja=ai_purpose_ja),
        VIEW_COMMON_TEMPLATE_LINES[2].format(help_ja_text=help_ja_text),
        VIEW_COMMON_TEMPLATE_LINES[3].format(model_tech=model_tech, model_table=model_table, primary_view_type=primary_view_type or ""),
    ]
    return "\n".join(lines)
