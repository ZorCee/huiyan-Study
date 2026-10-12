"""
眼底影像题库接口 (Question API)
- 逐图出题与指南挖空题出题
- 题干查重与模板自动生成
- 答题前脱敏下发
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.common.response import success
from app.db.models.user import RoleEnum
from app.schemas.question import QuestionCreateIn, TemplateGenerateIn, QuestionOut
from app.services.question_service import QuestionService

router = APIRouter(
    prefix="/question",
    tags=["10. 眼底影像题库（逐图题与指南挖空题）"],
    dependencies=[Depends(require_roles(RoleEnum.STUDENT, RoleEnum.TEACHER, RoleEnum.ADMIN))],
)


@router.post(
    "/create",
    summary="医生出题（支持逐图题与挖空题，含相似度查重拦截）",
    response_model=None,
    dependencies=[Depends(require_roles(RoleEnum.TEACHER, RoleEnum.ADMIN))],
)
def create_question(params: QuestionCreateIn, current_user: CurrentUser, db: DbSession):
    q = QuestionService.create_question(db, current_user, params.model_dump())
    return success(
        data={
            "id": q.id,
            "questionType": q.question_type,
            "caseId": q.case_id,
            "stem": q.stem,
            "sourceGuideline": q.source_guideline,
        },
        msg="题目创建成功",
    )


@router.get(
    "/templates",
    summary="获取系统内置的权威临床指南考点模板列表",
    response_model=None,
)
def get_guideline_templates():
    templates = QuestionService.list_guideline_templates()
    return success(data=templates)


@router.post(
    "/generate-by-template",
    summary="根据临床指南考点模板快速生成挖空题",
    response_model=None,
    dependencies=[Depends(require_roles(RoleEnum.TEACHER, RoleEnum.ADMIN))],
)
def generate_by_template(params: TemplateGenerateIn, current_user: CurrentUser, db: DbSession):
    q = QuestionService.generate_from_template(
        db, current_user, template_code=params.template_code, case_id=params.case_id
    )
    return success(
        data={
            "id": q.id,
            "stem": q.stem,
            "sourceGuideline": q.source_guideline,
            "blankConfig": q.blank_config,
        },
        msg="指南挖空题生成成功",
    )


@router.get(
    "/by-case/{caseId}",
    summary="按病例获取关联的逐图题与指南挖空题（答题前脱敏下发）",
    response_model=None,
)
def get_by_case(
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
    imageUrl: Optional[str] = Query(None, description="当前影像路径"),
):
    questions = QuestionService.get_questions_for_case(db, case_id=caseId, image_url=imageUrl)
    is_teacher = (
        current_user.role
        and current_user.role.code in (RoleEnum.TEACHER.value, RoleEnum.ADMIN.value)
    )

    out_list = []
    for q in questions:
        # 学生答题前脱敏屏蔽答案和解析
        item = {
            "id": q.id,
            "caseId": q.case_id,
            "imageId": q.image_id,
            "imageUrl": q.image_url,
            "questionType": q.question_type,
            "stem": q.stem,
            "options": q.options,
            "relatedAnnotationId": q.related_annotation_id,
            "roiBox": q.roi_box,
            "sourceGuideline": q.source_guideline,
            "sourceSection": q.source_section,
            "tags": q.tags,
            "difficulty": q.difficulty,
            "blankConfig": [
                {
                    "index": b.get("index"),
                    "key": b.get("key"),
                    "label": b.get("label"),
                }
                for b in (q.blank_config or [])
            ] if not is_teacher else q.blank_config,
            "answer": q.answer if is_teacher else None,
            "explanation": q.explanation if is_teacher else None,
        }
        out_list.append(item)

    return success(data=out_list)


@router.get(
    "/list",
    summary="题库列表检索",
    response_model=None,
)
def list_questions(
    db: DbSession,
    caseId: Optional[int] = Query(None),
    questionType: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    from app.db.models.question import Question

    q = db.query(Question).filter(Question.is_active == True)  # noqa: E712
    if caseId:
        q = q.filter(Question.case_id == caseId)
    if questionType:
        q = q.filter(Question.question_type == questionType)

    total = q.count()
    rows = q.order_by(Question.id.desc()).offset((page - 1) * pageSize).limit(pageSize).all()

    items = [
        {
            "id": r.id,
            "caseId": r.case_id,
            "imageId": r.image_id,
            "imageUrl": r.image_url,
            "questionType": r.question_type,
            "stem": r.stem,
            "options": r.options,
            "answer": r.answer,
            "sourceGuideline": r.source_guideline,
            "sourceSection": r.source_section,
            "tags": r.tags,
            "difficulty": r.difficulty,
            "relatedAnnotationId": r.related_annotation_id,
            "roiBox": r.roi_box,
            "explanation": r.explanation,
        }
        for r in rows
    ]
    return success(data={"total": total, "list": items, "page": page, "pageSize": pageSize})
