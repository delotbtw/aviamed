from fastapi import APIRouter, Depends

from app.core.deps import SessionDep, require_action
from app.core.rbac import Action
from app.reference.schemas import ExamProgramRead, ExamTypeRead, NamedRead
from app.reference.service import ReferenceService

router = APIRouter(
    prefix="/reference", tags=["reference"], dependencies=[Depends(require_action(Action.REFERENCE_READ))]
)


@router.get("/sports", response_model=list[NamedRead])
async def sports(session: SessionDep):
    return await ReferenceService(session).sports_list()


@router.get("/specialties", response_model=list[NamedRead])
async def specialties(session: SessionDep):
    return await ReferenceService(session).specialties_list()


@router.get("/exam-types", response_model=list[ExamTypeRead])
async def exam_types(session: SessionDep):
    return await ReferenceService(session).exam_types_list()


@router.get("/programs", response_model=list[ExamProgramRead])
async def programs(session: SessionDep):
    return await ReferenceService(session).programs_list()
