from typing import List

from sqlalchemy.orm import Session as DBSession

from app.auth.models import User, UserRole


class ACLResolver:
    """
    Resolves the set of ACL labels a user is permitted to access.

    Labels are assigned at ingest time; this resolver returns the matching set
    so the retriever can pre-filter OpenSearch results.

    Label conventions:
        dept_<name>    — uploaded by / belonging to a clinical department
        research_allowed — shared research content
        admin_only     — uploaded by an administrator account
    """

    @staticmethod
    def resolve_acl(db: DBSession, user_id: str) -> List[str]:
        user = db.query(User).filter_by(user_id=user_id).first()

        if not user:
            return []

        if user.role == UserRole.TREATING_CLINICIAN:
            dept = user.department or "unknown"
            # Treating clinicians see their department docs and admin-uploaded docs.
            return [f"dept_{dept}", "admin_only"]

        if user.role == UserRole.NON_TREATING_CLINICIAN:
            # Research users see shared research content and admin-uploaded docs.
            return ["research_allowed", "admin_only"]

        # ADMINISTRATOR — full read access for auditing purposes.
        return ["admin_only", "dept_cardiology", "research_allowed"]
