"""
旧接口兼容层：/reading/cases/{id}/lesion-seg 与 /ai-predict。

多病灶分割（VMUNet）与微动脉瘤分割都已改为调用 CSU-EYES 算法服务器，
本后端不再加载 PyTorch。实际调用见 ai_algorithm_service.py，
这里只把统一格式翻译回旧的 {available, counts, overlayUrl, message}。
"""

from __future__ import annotations

from typing import Optional

from app.db.models.user import User
from app.services.ai_algorithm_service import AiAlgorithmService

_LABELS = {"HE": "出血", "EX": "硬性渗出", "SE": "软性渗出"}

_LEGACY_NAME = {"multi_lesion": "multi_lesions", "ma_detection": "ma_detection"}


def _to_legacy(result: dict) -> dict:
    algorithm = result.get("algorithm") or "multi_lesion"
    default_counts = {"MA": 0} if algorithm == "ma_detection" else {"HE": 0, "EX": 0, "SE": 0}
    return {
        "available": result.get("status") == "done",
        "algorithm": _LEGACY_NAME.get(algorithm, algorithm),
        "algorithmName": result.get("algorithmName") or "",
        "overlayUrl": result.get("overlayUrl") or "",
        "counts": result.get("counts") or default_counts,
        "seconds": result.get("seconds") or 0,
        "message": result.get("message") or "",
    }


class LesionSegService:
    @staticmethod
    async def predict(
        db,
        user: User,
        case_id: int,
        image_url: str,
        algorithm: str = "multi_lesions",
        eye: Optional[str] = "",
    ) -> dict:
        result = await AiAlgorithmService.run(
            db, user, case_id, algorithm or "multi_lesion", image_url, eye or "",
        )
        return _to_legacy(result)
