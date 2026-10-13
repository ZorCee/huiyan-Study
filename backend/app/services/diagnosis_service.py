"""
CSU-EYES 诊断业务层
==================
- 处理「上传眼底图 + 调 CSU-EYES + 解析结果 + 写回病例」全链路
- 三种入口：
    1) MA 检测（单张）
    2) DR 分级（双眼）
    3) 综合诊断（单张多任务）
- 写入位置：
    - 影像本身 → ScreeningCase.image_paths（OD/OS/OU）
    - 推理结果 → ScreeningResult（每只眼一条；综合 = OU 一条）
    - heatmap / overlay 落盘 → /static/screening/...，URL 写入 ScreeningResult.heatmap_path
- 受检者信息：上传时选填编号 / 性别 / 年龄；未填写时生成「受检者-XXXX」编号，
  不再生成模拟姓名与手机号（字段说明见 docs/受检者信息字段说明.md）
- 返回值：DiagnosisOut（含 task_id / 主要展示字段 + 原始上游 JSON）

权限：上层路由用 require_roles(TEACHER, ADMIN) 控制。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.common.eye_infer import resolve_static_file, resolve_uploaded_eye
from app.common.utils import (
    resolve_screening_file,
    save_b64_image_to_screening,
    save_fundus_image,
)
from app.db.models import (
    DrGradeEnum,
    EyeSideEnum,
    GenderEnum,
    RiskLevelEnum,
    RoleEnum,
    ScreeningCase,
    ScreeningResult,
    ScreeningStatusEnum,
    User,
)
from app.schemas.diagnosis import (
    DiagnosisType,
    DrEyeResult,
    DiagnosisOut,
    MaDiagnosisResult,
    DrDiagnosisResult,
    ComprehensiveDiagnosisResult,
)
from app.services import csu_eyes_client


logger = logging.getLogger(__name__)


# ============================================================
#                    工具
# ============================================================

GRADE_TO_RISK = {
    "0": RiskLevelEnum.LOW.value,
    "1": RiskLevelEnum.LOW.value,
    "2": RiskLevelEnum.MEDIUM.value,
    "3": RiskLevelEnum.HIGH.value,
    "4": RiskLevelEnum.URGENT.value,
}


def _next_case_no(db: Session) -> str:
    """生成业务编号 D{YYYYMMDD}-XXXX，按当日记录数自增。"""
    from sqlalchemy import func
    today = datetime.now()
    prefix = f"D{today.strftime('%Y%m%d')}"
    cnt = (
        db.query(func.count(ScreeningCase.id))
        .filter(ScreeningCase.case_no.like(f"{prefix}%"))
        .scalar()
    ) or 0
    return f"{prefix}-{cnt + 1:04d}"


def _grade_str(v) -> str:
    """把 0~4 整数 / 数字字符串规范成 '0'~'4'，其它返回 '0'"""
    try:
        n = int(v)
    except Exception:
        return "0"
    if 0 <= n <= 4:
        return str(n)
    return "0"


AUTO_SUBJECT_PREFIX = "受检者-"
_MA_COUNT_KEYS = ("ma_count", "count", "num_ma", "total_ma", "total_count", "num_detections")
_MA_LIST_KEYS = ("detections", "boxes", "bboxes", "ma_list", "lesions")


@dataclass
class SubjectInput:
    """上传时选填的受检者信息。刻意不含姓名、手机号、身份证号。"""
    subject_code: str = ""
    gender: str = GenderEnum.UNKNOWN.value
    age: Optional[int] = None

    @property
    def provided(self) -> bool:
        return bool(self.subject_code)


def normalize_subject(
    subject_code: Optional[str], gender: Optional[str], age: Optional[int],
) -> SubjectInput:
    code = (subject_code or "").strip()[:32]
    g = (gender or "").strip().upper()
    if g not in (GenderEnum.MALE.value, GenderEnum.FEMALE.value):
        g = GenderEnum.UNKNOWN.value
    a = age if isinstance(age, int) and 0 <= age <= 130 else None
    return SubjectInput(subject_code=code, gender=g, age=a)


def display_subject_name(name: str) -> str:
    """自动编号原样显示；其它（历史模拟姓名等）只保留首字。"""
    name = (name or "").strip()
    if not name or name.startswith(AUTO_SUBJECT_PREFIX):
        return name
    return name[0] + "*" * max(1, len(name) - 1)


def _submitter_name(user: User) -> str:
    return (getattr(user, "real_name", "") or getattr(user, "username", "") or "").strip()


def extract_ma_count(block: Any) -> Optional[int]:
    """
    从上游 MA 结果块里取数量。找不到任何已知字段时返回 None，
    调用方据此显示「MA 未返回」，而不是把缺失当成 0。
    """
    if not isinstance(block, dict) or not block:
        return None
    # comprehensive 实际返回 {left_eye: {ma_count}, right_eye: {ma_count}}；
    # 同一张图会被同时当作左右眼送检，取较大值。
    per_eye = [
        extract_ma_count(block[k]) for k in _MA_EYE_KEYS if isinstance(block.get(k), dict)
    ]
    per_eye = [v for v in per_eye if v is not None]
    if per_eye:
        return max(per_eye)
    candidates = [block]
    for nested in ("result", "data"):
        if isinstance(block.get(nested), dict):
            candidates.append(block[nested])
    for c in candidates:
        for k in _MA_COUNT_KEYS:
            v = c.get(k)
            if v is None or isinstance(v, bool):
                continue
            try:
                return max(0, int(v))
            except (TypeError, ValueError):
                continue
        for k in _MA_LIST_KEYS:
            if isinstance(c.get(k), list):
                return len(c[k])
    return None


_MA_EYE_KEYS = ("right_eye", "left_eye", "OD", "OS")


def ma_image_block(block: Any) -> dict:
    """返回带 overlay_base64 的那一层（兼容 result 嵌套与左右眼嵌套）。"""
    if not isinstance(block, dict):
        return {}
    for k in _MA_EYE_KEYS:
        if isinstance(block.get(k), dict):
            return ma_image_block(block[k])
    if isinstance(block.get("result"), dict):
        return block["result"]
    return block


def sanitize_raw(raw: Any, _depth: int = 0) -> Any:
    """去掉 base64 图片与超长字符串，便于写日志排查。"""
    if _depth > 6:
        return "…"
    if isinstance(raw, dict):
        out = {}
        for k, v in raw.items():
            if isinstance(v, str) and ("base64" in str(k).lower() or len(v) > 300):
                out[k] = f"<str len={len(v)}>"
            else:
                out[k] = sanitize_raw(v, _depth + 1)
        return out
    if isinstance(raw, list):
        head = [sanitize_raw(v, _depth + 1) for v in raw[:5]]
        return head + ([f"<+{len(raw) - 5} items>"] if len(raw) > 5 else [])
    return raw


def _log_ma_missing(case: ScreeningCase, where: str, raw: Any) -> None:
    safe = sanitize_raw(raw)
    logger.warning(
        "[diagnosis] %s 未在上游响应中找到 MA 数量字段 case=%s raw=%s",
        where, case.case_no, json.dumps(safe, ensure_ascii=False, default=str)[:4000],
    )
    keys = list(raw.keys()) if isinstance(raw, dict) else []
    note = f"MA 未返回（{where}）；上游字段：{','.join(map(str, keys))}"
    case.remark = note[:255]


def _ma_risk(ma_count: Optional[int]) -> str:
    n = ma_count or 0
    if n >= 30:
        return RiskLevelEnum.HIGH.value
    if n >= 10:
        return RiskLevelEnum.MEDIUM.value
    return RiskLevelEnum.LOW.value


def _build_case(
    db: Session,
    *,
    user: User,
    diagnosis_type: DiagnosisType,
    image_paths: dict,
    image_count: int,
    remark: str,
    subject: Optional[SubjectInput] = None,
) -> ScreeningCase:
    """
    新建 ScreeningCase + case_sn。
    受检者：选填编号则按填写保存；否则用「受检者-XXXX」（取业务编号后 4 位），
    不再生成看似真实的模拟姓名 / 手机号。
    """
    from app.services.case_sn import generate_case_sn

    subject = subject or SubjectInput()
    case_no = _next_case_no(db)
    name = subject.subject_code or f"{AUTO_SUBJECT_PREFIX}{case_no[-4:]}"

    case = ScreeningCase(
        case_no=case_no,
        patient_name=name,
        patient_id_card="",
        gender=subject.gender,
        age=subject.age,
        phone="",
        patient_phone="",
        chief_complaint=f"CSU-EYES {diagnosis_type.value}",
        medical_history="",
        image_paths=image_paths,
        image_count=image_count,
        status=ScreeningStatusEnum.PROCESSING.value,
        submit_user_id=user.id,
        submit_at=datetime.now(),
        remark=remark or "",
    )
    try:
        case.case_sn = generate_case_sn(db)
    except Exception:
        pass
    db.add(case)
    db.flush()
    return case


# ============================================================
#                    Service
# ============================================================

class DiagnosisService:

    # ----------- 1. MA 检测 -----------
    @staticmethod
    async def ma_detection(
        db: Session,
        user: User,
        file: UploadFile,
        eye: str = "UK",
        model_id: Optional[int] = None,
        subject: Optional[SubjectInput] = None,
    ) -> DiagnosisOut:
        """单张眼底图 → MA 检测 → 写入新 ScreeningCase + ScreeningResult。"""
        subject = subject or SubjectInput()
        rel_url, file_name, _ = await save_fundus_image(file, user.id)
        requested = (eye or "").strip().upper()
        eye_db = resolve_uploaded_eye(
            requested if requested in ("OD", "OS", "OU") else "UK",
            file_name=file.filename or file_name,
            image_path=resolve_static_file(rel_url),
            role="original",
        )

        case = _build_case(
            db, user=user, diagnosis_type=DiagnosisType.MA,
            image_paths={eye_db: [rel_url]}, image_count=1,
            remark="CSU-EYES MA 检测", subject=subject,
        )

        # 调上游
        local_path = resolve_screening_file(rel_url)
        if local_path is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="影像落盘后未能定位本地文件",
            )
        try:
            raw = await csu_eyes_client.detect_ma(image_path=local_path, model_id=model_id)
        except HTTPException:
            case.status = ScreeningStatusEnum.FAILED.value
            db.commit()
            raise
        except Exception as e:
            case.status = ScreeningStatusEnum.FAILED.value
            case.remark = f"CSU-EYES 调用失败：{e}"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"CSU-EYES 调用失败：{e}",
            )

        ma_count = extract_ma_count(raw)
        if ma_count is None:
            _log_ma_missing(case, "ma-detection", raw)
        ma_src = ma_image_block(raw)
        overlay_url = save_b64_image_to_screening(
            ma_src.get("overlay_base64") or "",
            prefix="ma_overlay", case_no=case.case_no, suffix=eye_db.lower(),
        )
        heatmap_url = save_b64_image_to_screening(
            ma_src.get("heatmap_base64") or "",
            prefix="ma_heat", case_no=case.case_no, suffix=eye_db.lower(),
        )

        # 风险等级：按 MA 数量启发（>=10 中危，>=30 高危，否则正常）
        risk = _ma_risk(ma_count)
        n = ma_count or 0

        result = ScreeningResult(
            case_id=case.id,
            eye_side=eye_db,
            model_name="CSU-EYES MA",
            model_version="csu-v1",
            dr_grade=DrGradeEnum.G0.value,
            has_dme=False,
            risk_level=risk,
            risk_score=float(min(0.99, n / 50.0)),
            referral_required=n >= 30,
            lesions=[{"type": "MA", "count": ma_count}] if ma_count is not None else [],
            annotations=[],
            heatmap_path=overlay_url or heatmap_url or "",
            thumbnail_path=overlay_url or heatmap_url or "",
            infer_duration_ms=int(float(raw.get("inference_time") or 0) * 1000),
            inferred_at=datetime.now(),
        )
        db.add(result)
        case.status = ScreeningStatusEnum.COMPLETED.value
        db.commit()
        db.refresh(case)

        ma_res = MaDiagnosisResult(
            ma_count=ma_count,
            overlay_url=overlay_url,
            heatmap_url=heatmap_url,
            inference_time=float(raw.get("inference_time") or 0),
        )

        return DiagnosisOut(
            task_id=case.case_no,
            case_id=case.id,
            case_sn=case.case_sn or "",
            patient_name=display_subject_name(case.patient_name),
            subject_source="input" if subject.provided else "auto",
            submitter_name=_submitter_name(user),
            diagnosis_type=DiagnosisType.MA,
            risk_level=risk,
            primary_image_url=rel_url,
            ma=ma_res,
            raw=raw,
        )

    # ----------- 2. DR 双眼分级 -----------
    @staticmethod
    async def dr_grading(
        db: Session,
        user: User,
        left_eye: UploadFile,
        right_eye: UploadFile,
        model_id: Optional[int] = None,
        subject: Optional[SubjectInput] = None,
    ) -> DiagnosisOut:
        subject = subject or SubjectInput()
        left_url, _, _ = await save_fundus_image(left_eye, user.id)
        right_url, _, _ = await save_fundus_image(right_eye, user.id)

        case = _build_case(
            db, user=user, diagnosis_type=DiagnosisType.DR,
            image_paths={"OS": [left_url], "OD": [right_url]}, image_count=2,
            remark="CSU-EYES DR 分级", subject=subject,
        )

        left_p = resolve_screening_file(left_url)
        right_p = resolve_screening_file(right_url)
        if not left_p or not right_p:
            raise HTTPException(500, detail="DR 分级影像落盘后未能定位本地文件")

        try:
            raw = await csu_eyes_client.grade_dr(
                left_eye_path=left_p, right_eye_path=right_p, model_id=model_id,
            )
        except HTTPException:
            case.status = ScreeningStatusEnum.FAILED.value
            db.commit()
            raise

        left_grade = _grade_str(raw.get("left_eye_prediction"))
        right_grade = _grade_str(raw.get("right_eye_prediction"))
        overall = _grade_str(raw.get("overall_grade"))
        risk = GRADE_TO_RISK.get(overall, RiskLevelEnum.LOW.value)

        left_heatmap = save_b64_image_to_screening(
            raw.get("left_eye_heatmap_base64") or "",
            prefix="dr_heat", case_no=case.case_no, suffix="os",
        )
        right_heatmap = save_b64_image_to_screening(
            raw.get("right_eye_heatmap_base64") or "",
            prefix="dr_heat", case_no=case.case_no, suffix="od",
        )

        # 双眼各写一条 ScreeningResult
        for side, grade, heat in (
            ("OS", left_grade, left_heatmap),
            ("OD", right_grade, right_heatmap),
        ):
            db.add(ScreeningResult(
                case_id=case.id,
                eye_side=side,
                model_name="CSU-EYES DR",
                model_version="csu-v1",
                dr_grade=grade,  # DrGradeEnum 取值是 '0'~'4' 字符串
                has_dme=False,
                risk_level=GRADE_TO_RISK.get(grade, RiskLevelEnum.LOW.value),
                risk_score=float(int(grade) / 4.0),
                referral_required=int(grade) >= 3,
                lesions=[],
                annotations=[],
                heatmap_path=heat or "",
                thumbnail_path=heat or "",
                infer_duration_ms=int(float(raw.get("inference_time") or 0) * 1000),
                inferred_at=datetime.now(),
            ))

        case.status = ScreeningStatusEnum.COMPLETED.value
        db.commit()
        db.refresh(case)

        return DiagnosisOut(
            task_id=case.case_no,
            case_id=case.id,
            case_sn=case.case_sn or "",
            patient_name=display_subject_name(case.patient_name),
            subject_source="input" if subject.provided else "auto",
            submitter_name=_submitter_name(user),
            diagnosis_type=DiagnosisType.DR,
            risk_level=risk,
            primary_image_url=left_url,
            dr=DrDiagnosisResult(
                overall_grade=int(overall),
                overall_grade_name=str(raw.get("overall_grade_name") or ""),
                left=DrEyeResult(
                    grade=int(left_grade),
                    grade_name=str(raw.get("left_eye_grade_name") or ""),
                    image_url=left_url,
                    heatmap_url=left_heatmap,
                ),
                right=DrEyeResult(
                    grade=int(right_grade),
                    grade_name=str(raw.get("right_eye_grade_name") or ""),
                    image_url=right_url,
                    heatmap_url=right_heatmap,
                ),
                inference_time=float(raw.get("inference_time") or 0),
            ),
            raw=raw,
        )

    # ----------- 3. 综合诊断 -----------
    @staticmethod
    async def comprehensive(
        db: Session,
        user: User,
        file: UploadFile,
        tasks: Optional[List[str]] = None,
        subject: Optional[SubjectInput] = None,
    ) -> DiagnosisOut:
        subject = subject or SubjectInput()
        rel_url, file_name, _ = await save_fundus_image(file, user.id)
        eye_db = resolve_uploaded_eye(
            "UK",
            file_name=file.filename or file_name,
            image_path=resolve_static_file(rel_url),
            role="original",
        )
        case = _build_case(
            db, user=user, diagnosis_type=DiagnosisType.COMPREHENSIVE,
            image_paths={eye_db: [rel_url]}, image_count=1,
            remark="CSU-EYES 综合诊断", subject=subject,
        )

        local_path = resolve_screening_file(rel_url)
        if not local_path:
            raise HTTPException(500, detail="综合诊断影像落盘后未能定位本地文件")

        try:
            raw = await csu_eyes_client.comprehensive(image_path=local_path, tasks=tasks)
        except HTTPException:
            case.status = ScreeningStatusEnum.FAILED.value
            db.commit()
            raise

        results = raw.get("results") or {}
        ma_block = results.get("ma_detection") or {}
        dr_block = results.get("dr_grading") or {}

        ma_count = extract_ma_count(ma_block)
        wants_ma = not tasks or "ma_detection" in tasks
        if ma_count is None and wants_ma:
            # 综合接口没带回 MA 结果时，单独调一次 ma-detection 再合并，
            # 避免把「没跑 / 字段不同」误显示为 0 个。
            try:
                ma_raw = await csu_eyes_client.detect_ma(image_path=local_path)
            except HTTPException as e:
                logger.warning(
                    "[diagnosis] 综合诊断补调 ma-detection 失败 case=%s: %s",
                    case.case_no, e.detail,
                )
                ma_raw = {}
            ma_count = extract_ma_count(ma_raw)
            if ma_count is not None:
                ma_block = ma_raw
                raw = {**raw, "ma_detection_fallback": sanitize_raw(ma_raw)}
            else:
                _log_ma_missing(case, "comprehensive+ma-detection", raw)
        ma_overlay = save_b64_image_to_screening(
            ma_image_block(ma_block).get("overlay_base64") or "",
            prefix="comp_ma", case_no=case.case_no,
        )
        n = ma_count or 0

        overall = _grade_str(dr_block.get("overall_grade") or dr_block.get("prediction") or 0)
        risk_from_grade = GRADE_TO_RISK.get(overall, RiskLevelEnum.LOW.value)
        risk_from_ma = _ma_risk(ma_count)
        # 取风险更高的
        order = {
            RiskLevelEnum.LOW.value: 0,
            RiskLevelEnum.MEDIUM.value: 1,
            RiskLevelEnum.HIGH.value: 2,
            RiskLevelEnum.URGENT.value: 3,
        }
        risk = max([risk_from_grade, risk_from_ma], key=lambda r: order.get(r, 0))

        dr_heat = save_b64_image_to_screening(
            dr_block.get("heatmap_base64") or "",
            prefix="comp_dr", case_no=case.case_no,
        )

        db.add(ScreeningResult(
            case_id=case.id,
            eye_side=eye_db,
            model_name="CSU-EYES Comprehensive",
            model_version="csu-v1",
            dr_grade=overall,  # '0'~'4'
            has_dme=False,
            risk_level=risk,
            risk_score=float(int(overall) / 4.0),
            referral_required=int(overall) >= 3 or n >= 30,
            lesions=[{"type": "MA", "count": ma_count}] if ma_count is not None else [],
            annotations=[],
            heatmap_path=dr_heat or ma_overlay or "",
            thumbnail_path=ma_overlay or dr_heat or "",
            infer_duration_ms=int(float(raw.get("inference_time") or 0) * 1000),
            inferred_at=datetime.now(),
        ))
        case.status = ScreeningStatusEnum.COMPLETED.value
        db.commit()
        db.refresh(case)

        return DiagnosisOut(
            task_id=case.case_no,
            case_id=case.id,
            case_sn=case.case_sn or "",
            patient_name=display_subject_name(case.patient_name),
            subject_source="input" if subject.provided else "auto",
            submitter_name=_submitter_name(user),
            diagnosis_type=DiagnosisType.COMPREHENSIVE,
            risk_level=risk,
            primary_image_url=rel_url,
            comprehensive=ComprehensiveDiagnosisResult(
                overall_grade=int(overall),
                ma_count=ma_count,
                ma_overlay_url=ma_overlay,
                dr_heatmap_url=dr_heat,
                summary=str(raw.get("summary") or ""),
                inference_time=float(raw.get("inference_time") or 0),
            ),
            raw=raw,
        )


__all__ = ["DiagnosisService"]
