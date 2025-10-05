import json
import logging
from typing import Optional

logger = logging.getLogger("audit")


def log_ttype_change(*, model: str, field_name: str, old_ttype: str, new_ttype: str, actor: Optional[str] = None) -> None:
    payload = {
        "event": "ttype_changed",
        "model": model,
        "field_name": field_name,
        "old_ttype": old_ttype,
        "new_ttype": new_ttype,
        "actor": actor,
    }
    logger.info(json.dumps(payload, ensure_ascii=False))