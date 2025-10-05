from typing import Dict, Optional
from .html_strip import normalize_help_text

def normalize_model_name(model: Optional[str]) -> Optional[str]:
    if model is None:
        return None
    return model.strip().lower()


def merge_label_i18n(
    label_i18n: Optional[Dict[str, str]] = None,
    label_ja_jp: Optional[str] = None,
    label_en_us: Optional[str] = None,
) -> Dict[str, str]:
    """label_i18n を正とし、欠けている場合のみ ja_JP/en_US を補完。
    API 側のキーは ja/en だが、内部は ja_JP/en_US を使用。
    """
    merged: Dict[str, str] = {}
    if label_i18n:
        merged.update({k: v for k, v in label_i18n.items() if v is not None})
    if "ja_JP" not in merged and label_ja_jp:
        merged["ja_JP"] = label_ja_jp
    if "en_US" not in merged and label_en_us:
        merged["en_US"] = label_en_us
    return merged

def normalize_label(value: str | None) -> str:
    return (value or '').strip()


def normalize_longtext(value: str | None) -> str:
    return normalize_help_text(value)