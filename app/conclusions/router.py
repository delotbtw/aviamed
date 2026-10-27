from fastapi import APIRouter, Depends, Response, status

from app.conclusions.schemas import ClearanceStatus, ConclusionCreate, ConclusionRead
from app.conclusions.service import ConclusionService
from app.core.deps import SessionDep, require_action
from app.core.rbac import Action

router = APIRouter(prefix="/conclusions", tags=["conclusions"])


@router.post("", response_model=ConclusionRead, status_code=status.HTTP_201_CREATED)
async def issue(data: ConclusionCreate, session: SessionDep, actor=Depends(require_action(Action.CONCLUSION_ISSUE))):
    return await ConclusionService(session).issue(data, actor)


@router.get("/{case_id}/status", response_model=ClearanceStatus)
async def clearance_status(
    case_id: int, session: SessionDep, actor=Depends(require_action(Action.CLEARANCE_STATUS_VIEW))
):
    return await ConclusionService(session).clearance_status(case_id, actor)


@router.get("/{case_id}/pdf")
async def download_pdf(case_id: int, session: SessionDep, actor=Depends(require_action(Action.CONCLUSION_PDF))):
    pdf = await ConclusionService(session).render_pdf(case_id, actor)
    return Response(pdf, media_type="application/pdf")
