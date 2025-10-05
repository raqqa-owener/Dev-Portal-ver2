from typing import Dict, List
from sqlalchemy.orm import Session
from app.repos.portal_view_common_repo import PortalViewCommonRepo
from app.repos.portal_view_repo import PortalViewRepo


class BootstrapViewService:
    def __init__(self, sess: Session):
        self.sess = sess
        self.vc_repo = PortalViewCommonRepo(sess)
        self.v_repo = PortalViewRepo(sess)

    def bootstrap_by_action_xmlids(self, *, action_xmlids: List[str], set_primary_from_common: bool = True) -> Dict[str, int]:
        created = 0
        skipped = 0
        for axid in action_xmlids:
            try:
                vc = self.vc_repo.get_by_action_xmlid(axid)
            except Exception:
                skipped += 1
                continue

            common_id = vc["id"]
            model = vc.get("model") or vc.get("model_tech")
            view_types = vc.get("view_types") or []
            primary = vc.get("primary_view_type") if set_primary_from_common else None

            for vt in view_types:
                row = self.v_repo.upsert_skeleton(common_id=common_id, view_type=vt, model=model or "")
                created += 1 if row else 0
                if primary and vt == primary:
                    self.v_repo.set_primary_by_view_id(view_id=row["id"])  # DB トリガで単一化

        return {"created": created, "skipped": skipped}