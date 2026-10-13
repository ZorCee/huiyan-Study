"""正式考试：老师组卷、学员作答、收卷后导出成绩。"""

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response

from app.common.response import success
from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.db.models.user import RoleEnum
from app.schemas.exam import ExamCreate, ExamHandIn, ExamPreviewParams
from app.services.exam_service import ExamService

router = APIRouter(
    prefix="/exams",
    tags=["8b. 正式考试"],
    dependencies=[Depends(require_roles(RoleEnum.STUDENT, RoleEnum.TEACHER, RoleEnum.ADMIN))],
)


@router.get("/case-options", summary="可放入考试的实训病例")
def case_options(current_user: CurrentUser, db: DbSession):
    rows = ExamService.case_options(db, current_user)
    return success(data=[row.model_dump(by_alias=True) for row in rows])


@router.get("/audience-options", summary="发布考试时可选的受考对象及人数")
def audience_options(current_user: CurrentUser, db: DbSession):
    return success(ExamService.audience_options(db, current_user))


@router.post("/preview", summary="预览所选病例在考试里会出的题")
def preview_exam(params: ExamPreviewParams, current_user: CurrentUser, db: DbSession):
    return success(ExamService.preview(db, current_user, params.case_ids))


@router.get("", summary="考试列表")
def list_exams(current_user: CurrentUser, db: DbSession):
    rows = ExamService.list_papers(db, current_user)
    return success(data=[row.model_dump(by_alias=True) for row in rows])


@router.post("", summary="发布考试")
def create_exam(params: ExamCreate, current_user: CurrentUser, db: DbSession):
    data = ExamService.create(db, current_user, params)
    return success(data=data.model_dump(by_alias=True), msg="考试已发布")


@router.post("/{paperId}/start", summary="学员进入或继续考试（支持重考）")
def start_exam(
    current_user: CurrentUser,
    db: DbSession,
    paperId: int = Path(..., ge=1),
    retake: bool = Query(False, description="是否开启重考新轮次"),
):
    data = ExamService.start(db, current_user, paperId, retake=retake)
    return success(data=data.model_dump(by_alias=True))


@router.post("/{paperId}/draft", summary="允许返回时保存当前题")
def save_draft(
    params: ExamHandIn,
    current_user: CurrentUser,
    db: DbSession,
    paperId: int = Path(..., ge=1),
):
    from app.schemas.exam import hand_in_as_submit
    data = ExamService.save_draft(db, current_user, paperId, hand_in_as_submit(params))
    return success(data=data.model_dump(by_alias=True))


@router.post("/{paperId}/hand-in", summary="交卷。未作答的题目按未答计分")
def hand_in(
    params: ExamHandIn,
    current_user: CurrentUser,
    db: DbSession,
    paperId: int = Path(..., ge=1),
):
    data = ExamService.hand_in(db, current_user, paperId, params)
    return success(data=data.model_dump(by_alias=True), msg="已交卷")


@router.post("/{paperId}/collect", summary="统一收卷")
def collect(current_user: CurrentUser, db: DbSession, paperId: int = Path(..., ge=1)):
    data = ExamService.collect(db, current_user, paperId)
    return success(data=data, msg=data.get("message") or "已收卷")


@router.post("/{paperId}/students/{studentId}/reset", summary="重置学员的超时未作答空白卷")
def reset_attempt(
    current_user: CurrentUser,
    db: DbSession,
    paperId: int = Path(..., ge=1),
    studentId: int = Path(..., ge=1),
):
    data = ExamService.reset_attempt(db, current_user, paperId, studentId)
    return success(data=data, msg=data.get("message") or "已重置")


@router.get("/{paperId}/grades", summary="导出成绩")
def grades(current_user: CurrentUser, db: DbSession, paperId: int = Path(..., ge=1)):
    text = ExamService.csv_text(db, current_user, paperId)
    return Response(
        content=text.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=exam-grades.csv"},
    )


@router.delete("/{paperId}", summary="删除还没有人进入的考试")
def remove_exam(current_user: CurrentUser, db: DbSession, paperId: int = Path(..., ge=1)):
    ExamService.remove(db, current_user, paperId)
    return success(msg="已删除")
