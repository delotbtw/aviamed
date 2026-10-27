from fastapi import APIRouter, Depends

from app.core.deps import SessionDep, require_action, require_roles
from app.core.rbac import Action, Role
from app.examinations.schemas import ExaminationRead, ExamResultIn, StressTestIn
from app.examinations.service import ExaminationService

router = APIRouter(prefix="/examinations", tags=["examinations"])


@router.get("/{exam_id}", response_model=ExaminationRead)
async def get_exam(exam_id: int, session: SessionDep, actor=Depends(require_roles(Role.DOCTOR, Role.ATHLETE))):
    return await ExaminationService(session).get(exam_id, actor)


@router.post("/{exam_id}/result", response_model=ExaminationRead)
async def submit_result(
    exam_id: int, data: ExamResultIn, session: SessionDep, actor=Depends(require_action(Action.EXAM_RESULT_WRITE))
):
    return await ExaminationService(session).submit_result(exam_id, data, actor)


@router.post("/{exam_id}/stress-test", response_model=ExaminationRead)
async def submit_stress_test(
    exam_id: int, data: StressTestIn, session: SessionDep, actor=Depends(require_action(Action.STRESS_TEST_WRITE))
):
    return await ExaminationService(session).submit_stress_test(exam_id, data, actor)
