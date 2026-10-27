from fastapi import APIRouter, Depends, status

from app.cases.schemas import CaseCreate, CaseRead
from app.cases.service import CaseService
from app.core.deps import SessionDep, require_action, require_roles
from app.core.rbac import Action, Role

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
async def open_case(data: CaseCreate, session: SessionDep, actor=Depends(require_action(Action.CASE_OPEN))):
    return await CaseService(session).open_case(data, actor)


@router.get("", response_model=list[CaseRead])
async def list_cases(
    session: SessionDep,
    actor=Depends(require_roles(Role.ADMIN, Role.REGISTRAR, Role.ATHLETE, Role.COACH)),
):
    return await CaseService(session).list_for(actor)


@router.post("/{case_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_case(case_id: int, session: SessionDep, actor=Depends(require_action(Action.CASE_OPEN))) -> None:
    await CaseService(session).cancel(case_id, actor)
