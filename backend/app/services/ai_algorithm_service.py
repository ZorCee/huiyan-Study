"""
阅片页「AI算法判读」：算法目录 + 统一调用入口。

所有算法都在 CSU-EYES 算法服务器上运行，本后端只负责转发、落盘叠加图、
把各接口的返回整理成同一种格式。不写阅片记录，不改学员评分。

统一返回：
{
  "status": "done" | "failed" | "not_deployed",
  "algorithm", "algorithmName", "kind": "segmentation" | "classification",
  "overlayUrl", "counts": {...}, "classification": {label, labelEn, probabilities} | None,
  "metrics": {verticalCdr, horizontalCdr, riskLevel, riskName} | None,
  "seconds", "message"
}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from app.db.models.user import RoleEnum, User
from app.services import csu_eyes_client
from app.services.reading_service import ReadingService
from app.services.training_ai_service import _resolve_static_file

logger = logging.getLogger(__name__)

LESION_LABELS = {"EX": "硬性渗出", "SE": "软性渗出", "HE": "出血", "MA": "微动脉瘤"}

CATALOG: list[dict] = [
    {
        "key": "multi_lesion",
        "name": "多病灶分割",
        "kind": "segmentation",
        "taskType": "multi_lesion_segmentation",
        "model": "VMUNet",
        "endpoint": "/inference/multi-lesion-segmentation",
        "input": "单张眼底彩照（JPG/PNG）",
        "output": "EX / SE / HE 叠加图与各类像素数",
        "labels": ["EX", "SE", "HE"],
        "dependency": "CSU-EYES 算法服务器（torch、mamba_ssm、best_mdice.pth）",
        "teacherOnly": False,
    },
    {
        "key": "ma_detection",
        "name": "微动脉瘤分割",
        "kind": "segmentation",
        "taskType": "ma_detection",
        "model": "UNet-EfficientNetB4",
        "endpoint": "/inference/ma-detection",
        "input": "单张眼底彩照（JPG/PNG）",
        "output": "MA 叠加图与检出数量",
        "labels": ["MA"],
        "dependency": "CSU-EYES 算法服务器",
        "teacherOnly": False,
    },
    {
        "key": "ocod",
        "name": "视杯视盘分割（含杯盘比）",
        "kind": "segmentation",
        "taskType": "ocod_segmentation",
        "model": "VMUnet OCOD",
        "endpoint": "/inference/ocod-segmentation",
        "input": "单张眼底彩照（JPG/PNG），需包含视盘",
        "output": "视杯 / 视盘叠加图、垂直与水平杯盘比、风险等级",
        "labels": [],
        "dependency": "CSU-EYES 算法服务器",
        "teacherOnly": False,
    },
    {
        "key": "glaucoma",
        "name": "青光眼判别",
        "kind": "classification",
        "taskType": "glaucoma_screening",
        "model": "ConvNeXt-tiny",
        "endpoint": "/inference/glaucoma-screening",
        "input": "单张眼底彩照（JPG/PNG）",
        "output": "判别结论与各类概率",
        "labels": [],
        "dependency": "CSU-EYES 算法服务器",
        "teacherOnly": True,
    },
]
_BY_KEY = {item["key"]: item for item in CATALOG}

# IDRiD 病灶 / 结构颜色，与前端 src/utils/lesion-colors.ts 保持一致（回归测试比对）
LESION_COLORS: dict[str, str] = {
    "HE": "#f53f3f",
    "EX": "#ffd700",
    "SE": "#52c41a",
    "MA": "#eb2f96",
    "OD": "#1677ff",
    "NV": "#13c2c2",
}
# 旧前端参数名兼容
_ALIASES = {"multi_lesions": "multi_lesion"}


def _is_student(user: User) -> bool:
    return (user.role.code if user.role else "") == RoleEnum.STUDENT.value


def _visible(user: User) -> list[dict]:
    student = _is_student(user)
    return [item for item in CATALOG if not (student and item["teacherOnly"])]


def _allowed_urls(source) -> set[str]:
    allowed = {u for u in (source.images or []) if u}
    groups = source.image_groups or {}
    if isinstance(groups, dict):
        for urls in groups.values():
            for url in urls or []:
                if url:
                    allowed.add(url)
    return allowed


def _is_not_deployed(exc: HTTPException) -> bool:
    detail = str(exc.detail or "")
    return "CSU-EYES 404" in detail or "CSU-EYES 405" in detail


def _save_overlay(b64: str, algorithm: str, case_id: int, eye: str) -> str:
    if not b64:
        return ""
    from app.common.utils import save_b64_image_to_screening

    url = save_b64_image_to_screening(
        b64, prefix=f"ai_{algorithm}", case_no=str(case_id), suffix=(eye or "").lower(),
    )
    return url or f"data:image/png;base64,{b64}"


def _result(algorithm: str, status: str, message: str, **extra) -> dict:
    meta = _BY_KEY[algorithm]
    out = {
        "status": status,
        "algorithm": algorithm,
        "algorithmName": meta["name"],
        "kind": meta["kind"],
        "overlayUrl": "",
        "counts": {},
        "classification": None,
        "metrics": None,
        "seconds": 0,
        "message": message,
    }
    out.update(extra)
    return out


def _not_deployed(algorithm: str) -> dict:
    meta = _BY_KEY[algorithm]
    return _result(
        algorithm,
        "not_deployed",
        f"{meta['name']}尚未部署到 CSU-EYES 算法服务器（接口 {meta['endpoint']}），"
        "部署完成后即可使用。",
    )


def _to_float(value) -> Optional[float]:
    try:
        return None if value is None else round(float(value), 3)
    except (TypeError, ValueError):
        return None


async def _run_multi_lesion(path: Path, case_id: int, eye: str) -> dict:
    raw = await csu_eyes_client.segment_multi_lesion(image_path=path)
    body = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    pixel = body.get("pixel_counts") or body.get("counts") or {}
    counts = {key: int(pixel.get(key) or 0) for key in ("EX", "SE", "HE")}
    parts = [f"{LESION_LABELS[k]} {counts[k]} 像素" for k in ("EX", "SE", "HE")]
    return _result(
        "multi_lesion", "done", "多病灶分割完成：" + "，".join(parts) + "。",
        overlayUrl=_save_overlay(body.get("overlay_base64") or "", "multi_lesion", case_id, eye),
        counts=counts,
        seconds=float(raw.get("inference_time") or 0),
    )


async def _run_ma(path: Path, case_id: int, eye: str) -> dict:
    raw = await csu_eyes_client.detect_ma(image_path=path)
    count = int(raw.get("ma_count") or 0)
    return _result(
        "ma_detection", "done", f"微动脉瘤分割完成，共检出 {count} 处。",
        overlayUrl=_save_overlay(raw.get("overlay_base64") or "", "ma_detection", case_id, eye),
        counts={"MA": count},
        seconds=float(raw.get("inference_time") or 0),
    )


async def _run_ocod(path: Path, case_id: int, eye: str) -> dict:
    raw = await csu_eyes_client.segment_ocod(image_path=path)
    body = raw.get("result") or {}
    vertical = _to_float(body.get("vertical_cdr"))
    horizontal = _to_float(body.get("horizontal_cdr"))
    metrics = {
        "verticalCdr": vertical,
        "horizontalCdr": horizontal,
        "riskLevel": body.get("risk_level") or "unknown",
        "riskName": body.get("risk_name") or "",
        "cupAreaPx": int(body.get("cup_area_px") or 0),
        "discAreaPx": int(body.get("disc_area_px") or 0),
    }
    if vertical is None and horizontal is None:
        message = "视杯视盘分割完成，但未识别到视盘，无法计算杯盘比。请确认图像包含视盘区域。"
    else:
        shown = " / ".join(
            f"{name} {value:.2f}" for name, value in (("垂直", vertical), ("水平", horizontal))
            if value is not None
        )
        message = f"视杯视盘分割完成，杯盘比 {shown}。"
    return _result(
        "ocod", "done", message,
        overlayUrl=_save_overlay(body.get("overlay_base64") or "", "ocod", case_id, eye),
        metrics=metrics,
        seconds=float(raw.get("inference_time") or 0),
    )


async def _run_glaucoma(path: Path, case_id: int, eye: str) -> dict:
    raw = await csu_eyes_client.detect_glaucoma(image_path=path)
    body = raw.get("result") or {}
    probabilities = {
        str(k): float(v) for k, v in (body.get("probabilities") or {}).items()
        if isinstance(v, (int, float))
    }
    label = body.get("prediction_name") or ""
    return _result(
        "glaucoma", "done", f"青光眼判别：{label or '无结论'}。仅供带教参考，不作为诊断依据。",
        classification={
            "label": label,
            "labelEn": body.get("prediction_en") or "",
            "probabilities": probabilities,
        },
        seconds=float(raw.get("inference_time") or 0),
    )


_RUNNERS = {
    "multi_lesion": _run_multi_lesion,
    "ma_detection": _run_ma,
    "ocod": _run_ocod,
    "glaucoma": _run_glaucoma,
}


class AiAlgorithmService:
    @staticmethod
    def normalize(algorithm: str) -> str:
        key = (algorithm or "").strip()
        return _ALIASES.get(key, key)

    @staticmethod
    async def catalog(user: User) -> dict:
        items = [dict(item) for item in _visible(user)]
        reachable = True
        message = ""
        try:
            models = await csu_eyes_client.list_models()
            deployed = {str(m.get("task_type") or "") for m in models}
        except HTTPException as exc:
            reachable = False
            deployed = set()
            message = f"算法服务器暂时连不上：{exc.detail}"
        for item in items:
            if not reachable:
                item["status"] = "unreachable"
            elif item["taskType"] in deployed:
                item["status"] = "available"
            else:
                item["status"] = "not_deployed"
        return {"reachable": reachable, "message": message, "items": items}

    @staticmethod
    async def run(
        db, user: User, case_id: int, algorithm: str, image_url: str, eye: str = "",
    ) -> dict:
        key = AiAlgorithmService.normalize(algorithm)
        meta = _BY_KEY.get(key)
        if meta is None:
            raise HTTPException(status_code=400, detail=f"不支持的算法：{algorithm}")
        if meta["teacherOnly"] and _is_student(user):
            raise HTTPException(status_code=403, detail=f"{meta['name']}仅对带教老师和管理员开放")

        source = ReadingService.get_image_source(db=db, user=user, case_id=case_id)
        raw_url = (image_url or "").strip().split("?", 1)[0]
        if raw_url not in _allowed_urls(source):
            raise HTTPException(status_code=400, detail="这张图不属于当前病例")
        path = _resolve_static_file(raw_url)
        if path is None:
            raise HTTPException(status_code=400, detail="找不到这张眼底原图的文件")

        try:
            return await _RUNNERS[key](path, case_id, eye or "")
        except HTTPException as exc:
            if _is_not_deployed(exc):
                return _not_deployed(key)
            return _result(key, "failed", f"{meta['name']}调用失败：{exc.detail}")
        except Exception as exc:
            logger.exception("[ai-run] %s failed", key)
            return _result(key, "failed", f"{meta['name']}调用失败：{exc}")
