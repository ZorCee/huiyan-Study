"""
实训病例 AI 辅助诊断业务层
==========================
把 CSU-EYES 真实算法服务（DR 双眼分级 + GradCAM 热力图）接入教学端：

- 阅片工作站「AI 辅助诊断」：对当前实训病例执行真实推理，返回分级 + 热力图
- 练习自评「AI 参考」：学生提交后，展示 学生 vs AI vs 金标准 三方对比
- 教师端「AI 智能建案」：上传左右眼图 → AI 分级 → 生成实训病例草稿

结果缓存于 biz_training_ai_result（每病例一条，force=True 重跑覆盖），
避免学生每次打开都重复调用上游 GPU 服务。

上游 API：settings.CSU_EYES_BASE_URL（http://113.219.243.122:9050，勿用 9080）
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.common.utils import (
    project_root,
    save_b64_image_to_screening,
    save_fundus_image,
)
from app.core.config import settings
from app.db.models import TrainingAiResult, TrainingCase, User
from app.schemas.training_ai import (
    AiCaseDraftOut,
    AiDiagnosisOut,
    AiDiseaseResult,
    AiEyeResult,
    AiProb,
)
from app.services import case_findings, case_quality, csu_eyes_client
from app.services.training_service import DR_GRADE_TEXT

logger = logging.getLogger(__name__)


# ============================================================
#                    工具
# ============================================================

def _grade_int(v) -> int:
    try:
        n = int(v)
    except Exception:
        return 0
    return n if 0 <= n <= 4 else 0


def _grade_opt(v) -> Optional[int]:
    """与 _grade_int 不同：字段缺失或解析失败返回 None，不冒充 0 级。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        n = int(float(v))
    except Exception:
        return None
    return n if 0 <= n <= 4 else None


def _resolve_static_file(url: str) -> Optional[Path]:
    """
    把任意 /static/... 相对 URL 解析为磁盘绝对路径。
    限定在 UPLOAD_DIR（app/static）内，防路径越权；找不到返回 None。
    与 resolve_screening_file 的区别：实训病例影像可能位于
    /static/demo、/static/training 等子目录，不限于 screening。
    """
    if not url or not isinstance(url, str):
        return None
    raw = url.strip().split("?", 1)[0]
    static_prefix = settings.STATIC_URL.rstrip("/") + "/"
    if raw.startswith(static_prefix):
        rel = raw[len(static_prefix):]
    elif not raw.startswith("/"):
        rel = raw
    else:
        return None

    base = (project_root() / settings.UPLOAD_DIR).resolve()
    candidate = (base / rel).resolve()
    # 越权防护
    if base not in candidate.parents and candidate != base:
        return None
    return candidate if candidate.is_file() else None


def _original_eye_by_url(db: Session, case_id: int) -> dict:
    """原图 URL → 眼别。以 biz_case_image 为准，不信 image_paths 里过期的 OU 桶。"""
    from app.db.models import CaseImage

    rows = (
        db.query(CaseImage)
        .filter(
            CaseImage.case_table == "training",
            CaseImage.case_id == case_id,
            CaseImage.role == "original",
        )
        .all()
    )
    out = {}
    for row in rows:
        # 几十字节的占位文件不是另一只眼
        if (row.file_size or 0) < 500:
            continue
        url = (row.file_url or "").strip()
        if not url:
            continue
        eye = (row.eye or "").strip().upper()
        out[url] = eye if eye in ("OD", "OS", "OU", "UK") else "UK"
    return out


def _pick_eye_images(
    case: TrainingCase,
    eye_by_url: Optional[dict] = None,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    从 image_paths JSON 取 (左眼OS_url, 右眼OD_url, 要展示的眼别卡)。

    left / right 两个 URL 仍然都会填满 —— 算法接口要求两张图，
    单侧病例只能把同一张送两遍。但展示必须按真实眼别来。

    眼别以原图记录为准。image_paths 里很多单眼图仍挂在 OU（双眼）下，
    若只看这个桶，一张右眼图会被标成「双眼」。
    同一张文件同时出现在 OD 和 OS 里，也不是双眼。
    """
    paths = case.image_paths if isinstance(case.image_paths, dict) else {}
    known = eye_by_url or {}

    def _urls(side: str) -> List[str]:
        arr = paths.get(side) or []
        return [u for u in arr if isinstance(u, str) and u]

    collected: List[str] = []
    for side in ("OD", "OS", "OU", "UK"):
        for url in _urls(side):
            if url not in collected:
                collected.append(url)
    for url in known:
        if url and url not in collected:
            collected.append(url)

    grouped: dict = {"OD": [], "OS": [], "OU": [], "UK": []}
    for url in collected:
        eye = (known.get(url) or "").strip().upper()
        if eye not in grouped:
            eye = next((s for s in ("OD", "OS", "UK", "OU") if url in _urls(s)), "UK")
        if url not in grouped[eye]:
            grouped[eye].append(url)
        for other in ("OD", "OS", "OU", "UK"):
            if other != eye and url in grouped[other]:
                grouped[other].remove(url)

    od_url = grouped["OD"][0] if grouped["OD"] else None
    os_url = grouped["OS"][0] if grouped["OS"] else None
    ou_url = grouped["OU"][0] if grouped["OU"] else None
    uk_url = grouped["UK"][0] if grouped["UK"] else None

    if os_url and od_url and os_url != od_url:
        return os_url, od_url, ["left", "right"]
    if od_url:
        return od_url, od_url, ["right"]
    if os_url:
        return os_url, os_url, ["left"]
    if ou_url:
        return ou_url, ou_url, ["ou"]
    if uk_url:
        return uk_url, uk_url, ["unknown"]
    return None, None, []


async def _screen_glaucoma_both(left_p: Path, right_p: Path) -> Tuple[Optional[str], dict]:
    """两眼都测青光眼，取风险更高的一侧。返回 (AI 结论值, 原始结果)；都失败时结论为 None。"""
    best: Optional[Tuple[float, str, dict]] = None
    for eye, path in (("OS", left_p), ("OD", right_p)):
        try:
            raw = await csu_eyes_client.detect_glaucoma(image_path=path)
        except Exception as exc:
            logger.warning("[training-ai] 青光眼筛查失败 eye=%s: %s", eye, exc)
            continue
        res = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        pred = res.get("prediction")
        if pred is None:
            continue
        probs = res.get("probabilities") or {}
        risk = 0.0
        if isinstance(probs, dict):
            risk = float(probs.get("glaucoma") or probs.get("glaucoma_suspect") or 0)
        value = "S" if _grade_int(pred) >= 1 else "0"
        score = (1.0 if value == "S" else 0.0) + risk
        if best is None or score > best[0]:
            best = (score, value, {**raw, "eye": eye})
    if best is None:
        return None, {}
    return best[1], best[2]


def _get_case(db: Session, case_id: str) -> TrainingCase:
    """兼容 case_no（T2026001）与数字主键 id 两种形式。"""
    case = db.query(TrainingCase).filter(TrainingCase.case_no == case_id).first()
    if case is None and case_id.isdigit():
        case = db.query(TrainingCase).filter(TrainingCase.id == int(case_id)).first()
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"病例不存在：{case_id}",
        )
    return case


def _strip_b64(raw: dict) -> dict:
    """原始 JSON 去掉 base64 大字段后入库，避免撑爆 DB。"""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if not k.endswith("_base64")}


def _ai_value_for(case: TrainingCase, rec: TrainingAiResult, disease: str) -> Optional[str]:
    """从缓存的推理记录里取某病种的 AI 结论；没有判读过返回 None（不冒充 0）。"""
    primary = (case.category or "DR").upper()
    raw = rec.raw if isinstance(rec.raw, dict) else {}
    if disease == "GLAUCOMA":
        if primary == "GLAUCOMA":
            g = _grade_opt(rec.overall_grade)
            return None if g is None else ("S" if g >= 1 else "0")
        extra = raw.get("_glaucoma") if isinstance(raw.get("_glaucoma"), dict) else {}
        return extra.get("value") or None
    if disease == "DR" and primary != "GLAUCOMA":
        g = _grade_opt(rec.overall_grade)
        return None if g is None else str(g)
    return None


def _disease_results(
    case: TrainingCase, rec: TrainingAiResult, findings: List[dict]
) -> List[AiDiseaseResult]:
    out: List[AiDiseaseResult] = []
    for f in findings:
        if not f.get("value"):
            continue
        ai = _ai_value_for(case, rec, f["disease"])
        out.append(AiDiseaseResult(
            disease=f["disease"],
            disease_label=f.get("disease_label") or f["disease"],
            ai_value=ai,
            ai_label=(case_findings.value_label(f["disease"], ai) if ai is not None else "未判读"),
            gold_value=f["value"],
            gold_label=f.get("value_label") or f["value"],
            source=f.get("source") or "",
            agree=(ai == f["value"]) if ai is not None else None,
        ))
    return out


def _to_out(
    case: TrainingCase,
    rec: TrainingAiResult,
    *,
    left_url: str,
    right_url: str,
    single_eye: bool,
    eye_cards: List[str],
    cached: bool,
    findings: Optional[List[dict]] = None,
) -> AiDiagnosisOut:
    out = _to_out_primary(
        case, rec,
        left_url=left_url, right_url=right_url,
        single_eye=single_eye, eye_cards=eye_cards, cached=cached,
    )
    if findings:
        out.diseases = _disease_results(case, rec, findings)
    return out


def _to_out_primary(
    case: TrainingCase,
    rec: TrainingAiResult,
    *,
    left_url: str,
    right_url: str,
    single_eye: bool,
    eye_cards: List[str],
    cached: bool,
) -> AiDiagnosisOut:
    inferred_at = rec.updated_at or rec.created_at
    inferred_str = inferred_at.strftime("%Y-%m-%d %H:%M:%S") if inferred_at else ""
    category = (case.category or "DR").upper()

    # ---------- 青光眼：分类结果（非 DR 分级） ----------
    if category == "GLAUCOMA":
        raw = rec.raw if isinstance(rec.raw, dict) else {}
        res = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        pred = _grade_int(rec.overall_grade)
        pname = (res or {}).get("prediction_name") or (
            "青光眼疑似" if pred >= 1 else "未见明显青光眼"
        )
        gold_diag = (getattr(case, "gold_diagnosis", "") or "").strip()
        agree = (("青光眼" in gold_diag) == (pred >= 1)) if gold_diag else None

        _GLC_LABELS = {"normal": "正常", "glaucoma": "青光眼疑似", "glaucoma_suspect": "青光眼疑似"}
        probs_raw = (res or {}).get("probabilities") or {}
        probs: list = []
        if isinstance(probs_raw, dict):
            probs = [AiProb(label=_GLC_LABELS.get(k, k), value=float(v)) for k, v in probs_raw.items()]
            probs.sort(key=lambda x: x.value, reverse=True)

        def _eye(url: str, heat: str) -> AiEyeResult:
            return AiEyeResult(
                grade=pred, grade_text=pname, label=pname,
                image_url=url, heatmap_url=heat or "",
            )

        return AiDiagnosisOut(
            case_id=case.case_no,
            category="GLAUCOMA",
            probs=probs,
            overall_grade=pred,
            overall_grade_text=pname,
            overall_label=pname,
            left=_eye(left_url, rec.left_heatmap_path or ""),
            right=_eye(right_url, rec.right_heatmap_path or ""),
            single_eye=single_eye,
            eye_cards=eye_cards,
            gold_grade=None,
            gold_label=gold_diag,
            agree_with_gold=agree,
            model_name=rec.model_name or "CSU-EYES 青光眼筛查",
            infer_duration_ms=rec.infer_duration_ms or 0,
            cached=cached,
            inferred_at=inferred_str,
        )

    # ---------- DR：双眼分级（默认） ----------
    overall = _grade_int(rec.overall_grade)
    gold: Optional[int] = (
        int(case.gold_dr_grade) if (case.gold_dr_grade or "").isdigit() else None
    )
    return AiDiagnosisOut(
        case_id=case.case_no,
        category="DR",
        overall_grade=overall,
        overall_grade_text=DR_GRADE_TEXT.get(str(overall), ""),
        overall_label=f"DR {overall} 级",
        left=AiEyeResult(
            grade=_grade_int(rec.left_grade),
            grade_text=DR_GRADE_TEXT.get(str(_grade_int(rec.left_grade)), ""),
            label=f"DR {_grade_int(rec.left_grade)} 级",
            image_url=left_url,
            heatmap_url=rec.left_heatmap_path or "",
        ),
        right=AiEyeResult(
            grade=_grade_int(rec.right_grade),
            grade_text=DR_GRADE_TEXT.get(str(_grade_int(rec.right_grade)), ""),
            label=f"DR {_grade_int(rec.right_grade)} 级",
            image_url=right_url,
            heatmap_url=rec.right_heatmap_path or "",
        ),
        single_eye=single_eye,
        eye_cards=eye_cards,
        gold_grade=gold,
        gold_label=(f"DR {gold} 级" if gold is not None else ""),
        agree_with_gold=(overall == gold) if gold is not None else None,
        model_name=rec.model_name or "CSU-EYES DR",
        infer_duration_ms=rec.infer_duration_ms or 0,
        cached=cached,
        inferred_at=inferred_str,
    )


# ============================================================
#                    Service
# ============================================================

class TrainingAiService:

    # -------- 查询缓存（不触发推理） --------

    @staticmethod
    def get_cached(db: Session, case_id: str) -> Optional[AiDiagnosisOut]:
        case = _get_case(db, case_id)
        rec = (
            db.query(TrainingAiResult)
            .filter(TrainingAiResult.case_id == case.id)
            .first()
        )
        if rec is None:
            return None
        left_url, right_url, eye_cards = _pick_eye_images(
            case, _original_eye_by_url(db, case.id),
        )
        return _to_out(
            case, rec,
            left_url=left_url or "",
            right_url=right_url or "",
            single_eye=(left_url == right_url),
            eye_cards=eye_cards,
            cached=True,
            findings=case_findings.list_findings(db, case),
        )

    # -------- 执行 AI 诊断（带缓存） --------

    @staticmethod
    async def diagnose(
        db: Session,
        case_id: str,
        *,
        force: bool = False,
    ) -> AiDiagnosisOut:
        case = _get_case(db, case_id)

        rec = (
            db.query(TrainingAiResult)
            .filter(TrainingAiResult.case_id == case.id)
            .first()
        )
        left_url, right_url, eye_cards = _pick_eye_images(
            case, _original_eye_by_url(db, case.id),
        )
        single_eye = left_url == right_url
        findings = case_findings.list_findings(db, case)

        if rec is not None and not force:
            return _to_out(
                case, rec,
                left_url=left_url or "", right_url=right_url or "",
                single_eye=single_eye, eye_cards=eye_cards, cached=True,
                findings=findings,
            )

        if not left_url or not right_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该病例没有可用的眼底影像，无法执行 AI 诊断",
            )

        left_p = _resolve_static_file(left_url)
        right_p = _resolve_static_file(right_url)
        if left_p is None or right_p is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="病例影像文件缺失，无法送入算法服务（请管理员检查影像路径）",
            )

        # ========== 青光眼病例：调用青光眼筛查模型（单图分类，不做 DR 分级） ==========
        if (case.category or "").upper() == "GLAUCOMA":
            g_raw = await csu_eyes_client.detect_glaucoma(image_path=left_p)
            g_res = g_raw.get("result") if isinstance(g_raw.get("result"), dict) else {}
            pred = _grade_int((g_res or {}).get("prediction"))
            g_heat_b64 = (g_res or {}).get("heatmap_base64") or g_raw.get("heatmap_base64") or ""
            g_heat = (
                save_b64_image_to_screening(
                    g_heat_b64, prefix="tr_ai_heat", case_no=case.case_no, suffix="glc",
                )
                if g_heat_b64 else ""
            )
            g_ms = int(
                float(g_raw.get("inference_time") or (g_res or {}).get("inference_time") or 0) * 1000
            )
            probs = (g_res or {}).get("probabilities") or {}
            try:
                g_risk = float(max((v for k, v in probs.items() if k != "normal"), default=0)) \
                    if isinstance(probs, dict) else 0.0
            except Exception:
                g_risk = 0.0

            if rec is None:
                rec = TrainingAiResult(case_id=case.id)
                db.add(rec)
            rec.left_grade = rec.right_grade = rec.overall_grade = str(pred)
            rec.left_heatmap_path = g_heat
            rec.right_heatmap_path = g_heat
            rec.model_name = "CSU-EYES 青光眼筛查"
            rec.infer_duration_ms = g_ms
            rec.raw = _strip_b64(g_raw)
            rec.risk_score = g_risk
            db.commit()
            db.refresh(rec)
            logger.info(
                "[training-ai] GLAUCOMA case=%s pred=%s (%dms)",
                case.case_no, pred, g_ms,
            )
            return _to_out(
                case, rec,
                left_url=left_url, right_url=right_url,
                single_eye=single_eye, eye_cards=eye_cards, cached=False,
                findings=findings,
            )

        # ========== 其它（DR）：双眼分级 ==========
        raw = await csu_eyes_client.grade_dr(
            left_eye_path=left_p, right_eye_path=right_p,
        )

        left_grade = str(_grade_int(raw.get("left_eye_prediction")))
        right_grade = str(_grade_int(raw.get("right_eye_prediction")))
        overall = str(
            _grade_int(raw.get("overall_grade"))
            or max(int(left_grade), int(right_grade))
        )

        left_heat = save_b64_image_to_screening(
            raw.get("left_eye_heatmap_base64") or "",
            prefix="tr_ai_heat", case_no=case.case_no, suffix="os",
        )
        right_heat = save_b64_image_to_screening(
            raw.get("right_eye_heatmap_base64") or "",
            prefix="tr_ai_heat", case_no=case.case_no, suffix="od",
        )

        infer_ms = int(float(raw.get("inference_time") or 0) * 1000)
        try:
            risk = float(raw.get("right_eye_probability") or raw.get("left_eye_probability") or 0)
        except Exception:
            risk = 0.0

        if rec is None:
            rec = TrainingAiResult(case_id=case.id)
            db.add(rec)
        rec.left_grade = left_grade
        rec.right_grade = right_grade
        rec.overall_grade = overall
        rec.left_heatmap_path = left_heat or ""
        rec.right_heatmap_path = right_heat or ""
        stored = _strip_b64(raw)
        # 病例结论里还有青光眼时，两眼都测、取风险更高的一侧，一并给出 AI 结论
        if any(f["disease"] == "GLAUCOMA" and f["value"] for f in findings):
            gl_value, gl_raw = await _screen_glaucoma_both(left_p, right_p)
            stored["_glaucoma"] = {"value": gl_value, "eye": (gl_raw or {}).get("eye", "")}
            if gl_value is None:
                logger.warning("[training-ai] case=%s 青光眼筛查未返回结果", case.case_no)

        rec.model_name = "CSU-EYES DR"
        rec.infer_duration_ms = infer_ms
        rec.raw = stored
        rec.risk_score = risk
        db.commit()
        db.refresh(rec)

        logger.info(
            "[training-ai] case=%s OS=%s OD=%s overall=%s (%dms)",
            case.case_no, left_grade, right_grade, overall, infer_ms,
        )
        return _to_out(
            case, rec,
            left_url=left_url, right_url=right_url,
            single_eye=single_eye, eye_cards=eye_cards, cached=False,
            findings=findings,
        )

    # -------- 教师端：AI 智能建案 --------

    @staticmethod
    async def create_ai_case(
        db: Session,
        user: User,
        *,
        left_eye: UploadFile,
        right_eye: UploadFile,
        title: str = "",
        difficulty: str = "EASY",
        manual_dr: str = "",
        manual_glaucoma: str = "",
        screen_glaucoma: bool = False,
        confirm_low_quality: bool = False,
        confirm_laterality: bool = False,
        override_reason: str = "",
    ) -> AiCaseDraftOut:
        """
        上传左右眼底图 → CSU-EYES 分级 → 创建实训病例草稿（未发布）。
        金标准优先用教师人工预判；没填才用 AI 结果（来源标为 AI 待复核）。
        标题不参与分级，只在与金标准明显不一致时给出冲突提示。
        """
        left_url, _, _ = await save_fundus_image(left_eye, user.id)
        right_url, _, _ = await save_fundus_image(right_eye, user.id)

        left_p = _resolve_static_file(left_url)
        right_p = _resolve_static_file(right_url)
        if left_p is None or right_p is None:
            raise HTTPException(500, detail="影像落盘后未能定位本地文件")

        manual_dr = (manual_dr or "").strip()
        if manual_dr and not case_findings.valid_value("DR", manual_dr):
            raise HTTPException(400, detail="人工预判 DR 分级只能是 0~4，或不填")
        manual_glaucoma = (manual_glaucoma or "").strip().upper()
        if manual_glaucoma and not case_findings.valid_value("GLAUCOMA", manual_glaucoma):
            raise HTTPException(400, detail="人工预判青光眼只能是 有 / 无 / 疑似，或不填")

        # 质控在 AI 诊断之前：不合格就不跑分级，也不留下孤立文件
        quality_items = await case_quality.assess_upload([("OS", left_p), ("OD", right_p)])
        laterality = case_quality.laterality_conflicts([
            ("OS", left_eye.filename or ""), ("OD", right_eye.filename or ""),
        ])
        try:
            case_quality.gate(
                quality_items, laterality,
                confirm_low_quality=confirm_low_quality,
                confirm_laterality=confirm_laterality,
                override_reason=override_reason,
            )
        except HTTPException:
            for p in (left_p, right_p):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

        raw = await csu_eyes_client.grade_dr(
            left_eye_path=left_p, right_eye_path=right_p,
        )

        left_opt = _grade_opt(raw.get("left_eye_prediction"))
        right_opt = _grade_opt(raw.get("right_eye_prediction"))
        overall_opt = _grade_opt(raw.get("overall_grade"))
        if overall_opt is None and (left_opt is not None or right_opt is not None):
            overall_opt = max(g for g in (left_opt, right_opt) if g is not None)
        ai_returned = overall_opt is not None
        if not ai_returned:
            logger.warning(
                "[training-ai] 建案未取到 DR 分级，上游字段：%s",
                sorted(k for k in (raw or {}).keys() if not str(k).endswith("_base64")),
            )
        left_grade = left_opt if left_opt is not None else 0
        right_grade = right_opt if right_opt is not None else 0
        overall = overall_opt if overall_opt is not None else 0

        glaucoma_ai: Optional[str] = None
        glaucoma_raw: dict = {}
        if screen_glaucoma or manual_glaucoma:
            glaucoma_ai, glaucoma_raw = await _screen_glaucoma_both(left_p, right_p)

        dr_value, dr_source = case_findings.resolve(
            manual_dr, str(overall_opt) if ai_returned else None,
        )
        gl_value, gl_source = case_findings.resolve(manual_glaucoma, glaucoma_ai)

        # 生成新病例编号：T + 年份 + 3位自增
        from sqlalchemy import func
        year = datetime.now().strftime("%Y")
        prefix = f"T{year}"
        cnt = (
            db.query(func.count(TrainingCase.id))
            .filter(TrainingCase.case_no.like(f"{prefix}%"))
            .scalar()
        ) or 0
        case_no = f"{prefix}{cnt + 1:03d}"

        grade_text = DR_GRADE_TEXT.get(str(dr_value), f"{dr_value} 级") if dr_value else ""
        ai_text = (
            f"综合 DR {overall} 级，OS {left_grade} 级 / OD {right_grade} 级"
            if ai_returned else "AI 未返回 DR 分级"
        )
        if dr_source == "MANUAL":
            gold_diag = grade_text
            src_note = "金标准 DR 分级来自教师人工预判。"
        elif dr_value:
            gold_diag = f"（AI 预填，待复核）{grade_text}"
            src_note = "金标准为 AI 预填结果，请带教教师复核修订后发布。"
        else:
            gold_diag = ""
            src_note = "AI 未返回分级，请带教教师手动填写金标准。"
        if gl_value:
            gl_text = "青光眼" + case_findings.value_label("GLAUCOMA", gl_value)
            gold_diag = "；".join(x for x in (gold_diag, gl_text if gl_source == "MANUAL" else f"（AI 预填，待复核）{gl_text}") if x)
        case = TrainingCase(
            case_no=case_no,
            title=title.strip() or (f"AI 建案 · DR {dr_value} 级" if dr_value else "AI 建案"),
            description=f"由 CSU-EYES 算法服务自动建案（{ai_text}）。{src_note}",
            category="DR",
            difficulty=difficulty if difficulty in ("EASY", "MEDIUM", "HARD") else "EASY",
            patient_name="AI建案",
            patient_gender="U",
            image_paths={"OS": [left_url], "OD": [right_url]},
            gold_dr_grade=dr_value or "",
            gold_diagnosis=gold_diag,
            gold_lesions=[],
            gold_annotations=[],
            teaching_points="",
            is_published=False,
            is_train_case=False,
            creator_id=user.id,
        )
        try:
            from app.services.case_sn import generate_case_sn
            case.case_sn = generate_case_sn(db)
        except Exception:
            pass
        db.add(case)
        db.flush()

        # 热力图落盘 + AI 结果缓存
        left_heat = save_b64_image_to_screening(
            raw.get("left_eye_heatmap_base64") or "",
            prefix="tr_ai_heat", case_no=case_no, suffix="os",
        )
        right_heat = save_b64_image_to_screening(
            raw.get("right_eye_heatmap_base64") or "",
            prefix="tr_ai_heat", case_no=case_no, suffix="od",
        )
        case.gold_heatmap_path = right_heat or left_heat or ""

        rec = TrainingAiResult(
            case_id=case.id,
            left_grade=str(left_grade),
            right_grade=str(right_grade),
            overall_grade=str(overall),
            left_heatmap_path=left_heat or "",
            right_heatmap_path=right_heat or "",
            model_name="CSU-EYES DR",
            infer_duration_ms=int(float(raw.get("inference_time") or 0) * 1000),
            raw=_strip_b64(raw),
        )
        db.add(rec)
        if not ai_returned:
            rec.overall_grade = ""
            rec.left_grade = ""
            rec.right_grade = ""
        if glaucoma_raw:
            rec.raw = {**(rec.raw or {}), "glaucoma": _strip_b64(glaucoma_raw)}

        case_findings.upsert(
            db, case.id, "DR", value=dr_value, source=dr_source,
            ai_value=str(overall_opt) if ai_returned else None,
            confirmed_by=user.id if dr_source == "MANUAL" else None,
        )
        case_findings.upsert(
            db, case.id, "GLAUCOMA", value=gl_value, source=gl_source,
            ai_value=glaucoma_ai,
            confirmed_by=user.id if gl_source == "MANUAL" else None,
        )
        case_quality.persist(
            db, case, quality_items, user_id=user.id, override_reason=override_reason,
        )
        db.commit()
        db.refresh(case)
        db.refresh(rec)

        findings = case_findings.list_findings(db, case)
        return AiCaseDraftOut(
            id=case.id,
            case_id=case.case_no,
            title=case.title,
            is_published=False,
            ai=_to_out(
                case, rec,
                left_url=left_url, right_url=right_url,
                single_eye=False, eye_cards=["left", "right"], cached=False,
            ),
            ai_returned=ai_returned,
            findings=findings,
            conflicts=case_findings.conflicts(findings, case.title),
            quality=quality_items,
            quality_warnings=[case_quality.describe(i) for i in quality_items if case_quality.describe(i)],
            laterality=laterality,
            quality_override=case_quality.case_summary(db, case)["override"],
        )


__all__ = ["TrainingAiService"]
