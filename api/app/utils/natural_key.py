# natural_key build/validate
import re
from typing import Literal

_model_re = re.compile(r"^[a-z0-9._]+$")
_field_re = re.compile(r"^[a-z0-9_]+$")
_xmlid_re = re.compile(r"^[a-z0-9._]+$")

Target = Literal['ai_purpose', 'help']


def _ensure_no_sep(part: str):
    if '::' in part:
        raise ValueError("Parts must not contain '::'")


def build_field_key(model: str, field_name: str) -> str:
    m = (model or '').strip().lower()
    f = (field_name or '').strip().lower()
    _ensure_no_sep(m)
    _ensure_no_sep(f)
    if not _model_re.match(m):
        raise ValueError(f"Invalid model: {model}")
    if not _field_re.match(f):
        raise ValueError(f"Invalid field name: {field_name}")
    return f"field::{m}::{f}"


def build_view_common_key(action_xmlid: str, target: Target) -> str:
    x = (action_xmlid or '').strip().lower()
    _ensure_no_sep(x)
    if not _xmlid_re.match(x):
        raise ValueError(f"Invalid action_xmlid: {action_xmlid}")
    if target not in ('ai_purpose', 'help'):
        raise ValueError("target must be 'ai_purpose' or 'help'")
    return f"view_common::{x}::{target}"