"""
影像阅片路由
- 与前端 frontend/src/api/reading.ts 对齐
- 角色：STUDENT / TEACHER / ADMIN 均可访问，权限在 service 层细化
- 接口清单：
    GET    /reading/cases/{caseId}/source       获取病例影像源
    GET    /reading/cases/{caseId}/quality-result 读取已保存的图像质控结果
    GET    /reading/list                        阅片记录分页
    GET    /reading/{recordId}                  阅片记录详情
    GET    /reading/cases/{caseId}/draft        获取当前用户最新草稿（阅片页恢复用）
    POST   /reading/save                        保存（draft）/ 提交（submit=true）
    POST   /reading/{recordId}/review           教师审核（TEACHER/ADMIN）
    DELETE /reading/{recordId}                  删除（自己 DRAFT 或 ADMIN）
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from app.common.response import success
from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.db.models.user import RoleEnum
from app.schemas.reading import (
    ReadingListQuery,
    ReadingReviewParams,
    ReadingSaveParams,
)
from app.services.reading_service import ReadingService

router = APIRouter(
    prefix="/reading",
    tags=["7. 影像阅片"],
    dependencies=[Depends(require_roles(RoleEnum.STUDENT, RoleEnum.TEACHER, RoleEnum.ADMIN))],
)


@router.get(
    "/cases/{caseId}/source",
    summary="获取病例影像源（供前端 Cornerstone 加载）",
    response_model=None,
)
def get_image_source(
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
):
    data = ReadingService.get_image_source(db=db, user=current_user, case_id=caseId)
    return success(data=data.model_dump(by_alias=True))


@router.post(
    "/cases/{caseId}/quality-check",
    summary="评估病例原始影像的图像质量（先质量后诊断门控）",
    response_model=None,
)
async def check_image_quality(
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
):
    """
    调用 CSU-EYES 图像质量模型评估该病例的全部原始影像。

    算法服务不可用时不抛错：逐张记录失败原因，质量保持「未评估」，
    由界面如实呈现——绝不因为调用失败就把影像当作合格。
    """
    from app.services.image_quality_service import ImageQualityService

    data = await ImageQualityService.evaluate_case(db=db, case_id=caseId)
    data["reviewStatus"] = ""
    data["readingId"] = None
    role = current_user.role.code if current_user.role else ""
    if role == RoleEnum.STUDENT.value and int(data.get("evaluated") or 0) > 0:
        lines = [
            f"影像 {item.get('imageId')}：{item.get('quality')}"
            for item in (data.get("items") or [])
            if item.get("quality") and item.get("quality") != "unknown"
        ]
        note = "学员提交的图像质控记录，待教师审核。算法建议：" + ("；".join(lines) or "无")
        reviewed = ReadingService.submit_quality_review(
            db, current_user, caseId, note, {"qualityItems": data.get("items") or []},
        )
        data["reviewStatus"] = reviewed.status
        data["readingId"] = reviewed.id
    msg = "图像质控已完成并送交教师评审" if data.get("reviewStatus") == "SUBMITTED" else "图像质控完成"
    return success(data=data, msg=msg)


@router.get(
    "/cases/{caseId}/quality-result",
    summary="读取病例每张原图已保存的图像质控结果（不调用算法）",
    response_model=None,
)
def get_image_quality_result(
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
):
    from app.services.image_quality_service import ImageQualityService

    # 与影像源同一套可见性校验：看不到病例影像的人也看不到质控结果
    ReadingService.get_image_source(db=db, user=current_user, case_id=caseId)
    return success(data=ImageQualityService.case_result(db, caseId))


class LesionSegParams(BaseModel):
    """只带当前眼底图地址。不改已有阅片保存结构。"""

    model_config = ConfigDict(populate_by_name=True)
    image_url: str = Field(..., alias="imageUrl", min_length=1)


class AiPredictParams(BaseModel):
    """AI 预测图推理参数，支持算法 A (VM-UNet 多病灶) 与算法 B (CSU-EYES 微动脉瘤)"""

    model_config = ConfigDict(populate_by_name=True)
    image_url: str = Field(..., alias="imageUrl", min_length=1)
    algorithm: str = Field("multi_lesions", alias="algorithm")
    eye: Optional[str] = Field(None, alias="eye")


class AiRunParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    algorithm: str = Field(..., min_length=1)
    image_url: str = Field(..., alias="imageUrl", min_length=1)
    eye: Optional[str] = Field(None)


@router.get(
    "/ai-algorithms",
    summary="AI算法目录（名称、类型、入参出参、依赖）与 CSU-EYES 实时部署状态",
    response_model=None,
)
async def list_ai_algorithms(current_user: CurrentUser):
    from app.services.ai_algorithm_service import AiAlgorithmService

    return success(data=await AiAlgorithmService.catalog(current_user))


@router.post(
    "/cases/{caseId}/ai-run",
    summary="对当前眼底图运行单个 AI 算法（多病灶 / 微动脉瘤 / 视杯视盘 / 青光眼）",
    response_model=None,
)
async def run_ai_algorithm(
    params: AiRunParams,
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
):
    from app.services.ai_algorithm_service import AiAlgorithmService

    data = await AiAlgorithmService.run(
        db=db, user=current_user, case_id=caseId,
        algorithm=params.algorithm, image_url=params.image_url, eye=params.eye or "",
    )
    return success(data=data, msg=data.get("message") or "")


@router.post(
    "/cases/{caseId}/ai-predict",
    summary="对当前眼底图执行真实 AI 预测算法（多病灶分割 / 微动脉瘤分割）",
    response_model=None,
)
async def predict_case_ai(
    params: AiPredictParams,
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
):
    """
    接入两套真实算法：
    1. multi_lesions: VM-UNet（出血、硬性渗出、软性渗出）
    2. ma_detection: CSU-EYES 微动脉瘤分割
    解耦金标准，服务不可用时如实返回错误，绝不伪造数据。
    """
    from app.services.lesion_seg_service import LesionSegService

    data = await LesionSegService.predict(
        db=db,
        user=current_user,
        case_id=caseId,
        image_url=params.image_url,
        algorithm=params.algorithm,
        eye=params.eye,
    )
    return success(data=data, msg=data.get("message") or "")


@router.post(
    "/cases/{caseId}/lesion-seg",
    summary="对当前眼底图做出血、硬性渗出、软性渗出分割",
    response_model=None,
)
async def segment_lesions(
    params: LesionSegParams,
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
):
    """
    兼容保留旧接口：多病灶分割，改为调用 CSU-EYES 算法服务器。
    """
    from app.services.lesion_seg_service import LesionSegService

    data = await LesionSegService.predict(
        db=db, user=current_user, case_id=caseId, image_url=params.image_url,
    )
    return success(data=data, msg=data.get("message") or "")



@router.get(
    "/cases/{caseId}/diagnosis-form",
    summary="按病种取结构化诊断表单定义",
    response_model=None,
)
def diagnosis_form_def(
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
):
    """
    表单由配置定义、按病种加载，新增病种只加配置不改代码。

    字段顺序遵循报告建议：质量 → 主要结论 → 关键征象 → 分级 →
    置信度 → 处置，渐进展开而非一次铺开全部字段。
    """
    from app.common import diagnosis_form
    from app.db.models import TrainingCase

    case = db.query(TrainingCase).filter(TrainingCase.id == caseId).first()
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    materials = diagnosis_form.materials_for_case(db, case)
    return success(data=diagnosis_form.get_form(case.category, materials))


@router.get(
    "/cases/{caseId}/draft",
    summary="恢复当前用户在该病例的最新阅片草稿（可能为空）",
    response_model=None,
)
def get_latest_draft(
    current_user: CurrentUser,
    db: DbSession,
    caseId: int = Path(..., ge=1),
    imageIndex: int = Query(0, ge=0),
):
    data = ReadingService.get_latest_draft(
        db=db, user=current_user, case_id=caseId, image_index=imageIndex,
    )
    return success(data=data.model_dump(by_alias=True) if data else None)


@router.get(
    "/list",
    summary="阅片记录分页查询",
    response_model=None,
)
def list_records(
    current_user: CurrentUser,
    db: DbSession,
    caseId: Optional[int] = Query(None, ge=1),
    userId: Optional[int] = Query(None, ge=1),
    status: Optional[str] = Query(None, description="DRAFT/SUBMITTED/REVIEWED"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
):
    query = ReadingListQuery(
        case_id=caseId,
        user_id=userId,
        status=status,  # type: ignore[arg-type]
        page=page,
        page_size=pageSize,
    )
    data = ReadingService.list_records(db=db, user=current_user, query=query)
    return success(data=data.model_dump(by_alias=True))


@router.get(
    "/{recordId}",
    summary="阅片记录详情",
    response_model=None,
)
def get_detail(
    current_user: CurrentUser,
    db: DbSession,
    recordId: int = Path(..., ge=1),
):
    data = ReadingService.get_detail(db=db, user=current_user, record_id=recordId)
    return success(data=data.model_dump(by_alias=True))


@router.post(
    "/save",
    summary="保存阅片标注（DRAFT，submit=true 时为 SUBMITTED）",
    response_model=None,
)
def save_reading(
    params: ReadingSaveParams,
    current_user: CurrentUser,
    db: DbSession,
):
    data = ReadingService.save(db=db, user=current_user, params=params)
    msg = "已提交" if params.submit else "已保存"
    return success(data=data.model_dump(by_alias=True), msg=msg)


@router.post(
    "/{recordId}/review",
    summary="教师审核阅片记录（TEACHER/ADMIN）",
    response_model=None,
)
def review_reading(
    params: ReadingReviewParams,
    current_user: CurrentUser,
    db: DbSession,
    recordId: int = Path(..., ge=1),
):
    data = ReadingService.review(
        db=db, user=current_user, record_id=recordId, params=params,
    )
    return success(data=data.model_dump(by_alias=True), msg="审核完成")


@router.delete(
    "/{recordId}",
    summary="删除阅片记录（自己草稿 / ADMIN）",
    response_model=None,
)
def delete_reading(
    current_user: CurrentUser,
    db: DbSession,
    recordId: int = Path(..., ge=1),
):
    ReadingService.delete(db=db, user=current_user, record_id=recordId)
    return success(msg="已删除")
