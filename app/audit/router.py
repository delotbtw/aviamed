from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.audit.schemas import AuditRead
from app.composition import AuditRepoDep
from app.core.deps import require_action
from app.core.rbac import Action

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_action(Action.AUDIT_VIEW))])


@router.get("", response_model=list[AuditRead])
async def audit_log(
    audit: AuditRepoDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await audit.list_recent(limit=limit, offset=offset)
