from fastapi import APIRouter, Depends

from app.audit.schemas import AuditRead
from app.audit.service import AuditService
from app.core.deps import SessionDep, require_action
from app.core.rbac import Action

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_action(Action.AUDIT_VIEW))])


@router.get("", response_model=list[AuditRead])
async def audit_log(session: SessionDep, limit: int = 100, offset: int = 0):
    return await AuditService(session).recent(limit, offset)
