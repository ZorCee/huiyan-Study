# -*- coding: utf-8 -*-
"""
AI 建案的图像质控门控。

在 AI 诊断之前执行，结论由后端决定，前端绕不过去：
    好 / 可用      → 正常建案
    差             → 409 QUALITY_POOR，确认后带 confirm_low_quality 重新提交
    不可判读        → 409 QUALITY_UNGRADABLE，只能重新上传或填理由人工放行
    质控服务不可用  → 不阻断，记为「未评估」
    眼别冲突        → 409 LATERALITY_CONFLICT，确认眼别后继续

结果写入现有 biz_case_image_quality；人工放行写病例上的留痕字段。
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.common.image_safety import (
    EYE_TEXT,
    UNKNOWN_QUALITY,
    detect_laterality_conflict,
    quality_text,
)
from app.db.models.case_image import CaseImage
from app.db.models.case_image_quality import CaseImageQuality
from app.db.models.training_case import TrainingCase
from app.services.image_precheck import precheck

logger = logging.getLogger(__name__)

LOW_QUALITY = ("poor", "ungradable")
PRECHECK_MODEL = "本地预检"
OVERRIDE_REASON_MAX = 255


def _item(eye: str, *, quality: str = UNKNOWN_QUALITY, confidence: float = 0.0,
          probabilities: Optional[dict] = None, model_name: str = "",
          reason: str = "", error: str = "", source: str = "NONE",
          duration_ms: int = 0) -> dict:
    return {
        "eye": eye,
        "eyeText": EYE_TEXT.get(eye, eye),
        "quality": quality,
        "qualityText": quality_text(quality),
        "confidence": round(float(confidence or 0.0), 4),
        "probabilities": probabilities or {},
        "modelName": model_name,
        "reason": reason,
        "error": error,
        "source": source,
        "durationMs": duration_ms,
    }


def describe(item: dict) -> str:
    """弹窗里一行原因。模型只给总体等级，不编造分维度结论。"""
    eye = item["eyeText"]
    if item["quality"] == "ungradable":
        return f"{eye}图像不可判读：{item['reason']}"
    if item["quality"] == "poor":
        pct = round(item["confidence"] * 100)
        return f"{eye}图像质量较差（质控模型判定：差，置信度 {pct}%），AI 分级结果可能不准确"
    return ""


async def assess_upload(images: List[tuple]) -> List[dict]:
    """
    images: [(eye, local_path), ...]
    预检命中直接判为不可判读，不再调用模型；
    模型异常或返回无法识别时记为未评估，绝不当作合格。
    """
    from app.services import csu_eyes_client
    from app.services.image_quality_service import parse_upstream

    items = []
    for eye, path in images:
        reason = precheck(Path(path))
        if reason:
            items.append(_item(eye, quality="ungradable", reason=reason,
                               model_name=PRECHECK_MODEL, source="PRECHECK"))
            continue
        started = time.time()
        try:
            payload = await csu_eyes_client.assess_image_quality(image_path=Path(path))
            parsed = parse_upstream(payload)
        except Exception as exc:  # noqa: BLE001 —— 质控服务不可用时降级为未评估
            logger.warning("[case-quality] 质控调用失败 eye=%s: %s", eye, exc)
            items.append(_item(eye, error="质控服务暂不可用"))
            continue
        cost = int((time.time() - started) * 1000)
        if parsed.get("quality") == UNKNOWN_QUALITY:
            items.append(_item(eye, error="质控模型已返回，但没有可识别的质量等级",
                               duration_ms=cost))
            continue
        items.append(_item(
            eye, quality=parsed["quality"], confidence=parsed.get("confidence") or 0.0,
            probabilities=parsed.get("probabilities") or {},
            model_name=parsed.get("model_name") or "", source="MODEL", duration_ms=cost,
        ))
    return items


def laterality_conflicts(files: List[tuple]) -> List[str]:
    """files: [(eye, original_file_name), ...]"""
    out = []
    for eye, name in files:
        msg = detect_laterality_conflict(eye=eye, file_name=name or "")
        if msg:
            out.append(f"{EYE_TEXT.get(eye, eye)}上传位：{msg}")
    return out


def gate(
    items: List[dict],
    laterality: List[str],
    *,
    confirm_low_quality: bool,
    confirm_laterality: bool,
    override_reason: str,
) -> None:
    """不满足继续条件时抛 409，detail 里带质控结果供前端弹窗。"""
    reason = (override_reason or "").strip()
    ungradable = [i for i in items if i["quality"] == "ungradable"]
    poor = [i for i in items if i["quality"] == "poor"]

    def _reject(kind: str, message: str, reasons: List[str]):
        raise HTTPException(409, detail={
            "kind": kind,
            "message": message,
            "reasons": reasons,
            "quality": items,
            "laterality": laterality,
        })

    if laterality and not confirm_laterality:
        _reject("LATERALITY_CONFLICT", "左右眼可能放反了，请确认眼别后再继续", laterality)
    if ungradable and not reason:
        _reject("QUALITY_UNGRADABLE", "图像不可判读，已阻止建案",
                [describe(i) for i in ungradable])
    if poor and not (confirm_low_quality or reason):
        _reject("QUALITY_POOR", "图像质量较差，AI 分级结果可能不准确",
                [describe(i) for i in poor])
    if reason and len(reason) > OVERRIDE_REASON_MAX:
        raise HTTPException(400, detail=f"放行理由不能超过 {OVERRIDE_REASON_MAX} 字")


def needs_override(items: List[dict]) -> bool:
    return any(i["quality"] == "ungradable" for i in items)


def persist(db: Session, case: TrainingCase, items: List[dict], *,
            user_id: int, override_reason: str) -> None:
    """登记原图并写入质控结果；不可判读放行时在病例上留痕。不提交事务。"""
    from app.services.case_image_service import CaseImageService

    db.flush()
    images = CaseImageService.ensure_training_case_images(db, case_id=case.id)
    paths = case.image_paths or {}
    by_eye = {}
    for img in images:
        by_eye.setdefault((img.eye or "").upper(), img)
        for eye, urls in paths.items():
            if isinstance(urls, list) and img.file_url in urls:
                by_eye[eye.upper()] = img

    now = datetime.now()
    for item in items:
        img = by_eye.get(item["eye"])
        if img is None:
            continue
        row = (
            db.query(CaseImageQuality)
            .filter(CaseImageQuality.case_image_id == img.id)
            .first()
        )
        if row is None:
            row = CaseImageQuality(case_image_id=img.id)
            db.add(row)
        row.quality = item["quality"]
        row.confidence = item["confidence"]
        row.probabilities = item["probabilities"]
        row.model_name = item["modelName"]
        row.error_msg = (item["error"] or item["reason"] or "")[:255]
        row.infer_duration_ms = int(item["durationMs"] or 0)
        row.checked_at = now

    reason = (override_reason or "").strip()
    if reason and needs_override(items):
        case.quality_override_by = user_id
        case.quality_override_at = now
        case.quality_override_reason = reason[:OVERRIDE_REASON_MAX]


def low_quality_case_ids(db: Session):
    """存在差 / 不可判读原图的实训病例 id 子查询。"""
    return (
        db.query(CaseImage.case_id)
        .join(CaseImageQuality, CaseImageQuality.case_image_id == CaseImage.id)
        .filter(
            CaseImage.case_table == "training",
            CaseImage.role == "original",
            CaseImageQuality.quality.in_(LOW_QUALITY),
        )
        .distinct()
    )


def exclude_low_quality(q):
    """练习 / 考试抽题默认排除低质量病例。历史病例无质控记录，不受影响。"""
    db = q.session
    return q.filter(~TrainingCase.id.in_(low_quality_case_ids(db)))


def filter_by_level(q, level: str):
    """金标准列表的「图像质控」筛选：LOW / OK / UNKNOWN。"""
    db = q.session
    low = low_quality_case_ids(db)
    evaluated = (
        db.query(CaseImage.case_id)
        .join(CaseImageQuality, CaseImageQuality.case_image_id == CaseImage.id)
        .filter(
            CaseImage.case_table == "training",
            CaseImage.role == "original",
            CaseImageQuality.quality != UNKNOWN_QUALITY,
        )
        .distinct()
    )
    if level == "LOW":
        return q.filter(TrainingCase.id.in_(low))
    if level == "OK":
        return q.filter(TrainingCase.id.in_(evaluated), ~TrainingCase.id.in_(low))
    if level == "UNKNOWN":
        return q.filter(~TrainingCase.id.in_(evaluated))
    return q


def case_summary(db: Session, case: TrainingCase) -> dict:
    """病例页横幅用：最差等级、每眼结果、放行留痕。"""
    rows = (
        db.query(CaseImage.eye, CaseImageQuality.quality, CaseImageQuality.confidence)
        .join(CaseImageQuality, CaseImageQuality.case_image_id == CaseImage.id)
        .filter(
            CaseImage.case_table == "training",
            CaseImage.case_id == case.id,
            CaseImage.role == "original",
        )
        .all()
    )
    order = {"ungradable": 0, "poor": 1, "usable": 2, "good": 3}
    graded = [r for r in rows if r[1] in order]
    worst = min(graded, key=lambda r: order[r[1]])[1] if graded else UNKNOWN_QUALITY
    override = None
    if getattr(case, "quality_override_at", None):
        override = {
            "by": case.quality_override_by,
            "at": case.quality_override_at.isoformat(sep=" ", timespec="seconds"),
            "reason": case.quality_override_reason or "",
        }
    return {
        "level": worst,
        "levelText": quality_text(worst),
        "lowQuality": worst in LOW_QUALITY,
        "eyes": [
            {"eye": (e or "").upper(), "eyeText": EYE_TEXT.get((e or "").upper(), "眼别未知"),
             "quality": q, "qualityText": quality_text(q), "confidence": float(c or 0.0)}
            for e, q, c in rows
        ],
        "override": override,
    }


__all__ = [
    "assess_upload", "laterality_conflicts", "gate", "persist", "describe",
    "exclude_low_quality", "filter_by_level", "case_summary", "low_quality_case_ids",
]
