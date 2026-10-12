"""
教师端多病灶分割。

算法来自 D:\\huiyan\\multi_lesions_seg.zip：VM-UNet，类别为背景、出血(HE)、
硬性渗出(EX)、软性渗出(SE)。推理代码在 backend/vendor/multi_lesions_seg，
权重在 backend/data/multi_lesions/best_mdice.pth（不进仓库）。

这里只生成叠加图，不写阅片记录，不改学员评分，也不代替 CSU-EYES 分级。
启动时不加载 PyTorch；缺依赖时接口如实返回 available=false。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from app.common.utils import project_root
from app.core.config import settings
from app.db.models.user import RoleEnum, User
from app.services.reading_service import ReadingService
from app.services.training_ai_service import _resolve_static_file

_LABELS = {"HE": "出血", "EX": "硬性渗出", "SE": "软性渗出"}
_loaded_model = None


def _vendor_root() -> Path:
    return project_root() / "vendor" / "multi_lesions_seg"


def _weight_file() -> Optional[Path]:
    candidates = []
    if settings.MULTI_LESION_WEIGHTS:
        candidates.append(Path(settings.MULTI_LESION_WEIGHTS))
    candidates.append(project_root() / "data" / "multi_lesions" / "best_mdice.pth")
    candidates.append(Path(r"D:/huiyan/multi_lesions_seg/weights/best_mdice.pth"))
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 1_000_000:
                return path
        except OSError:
            continue
    return None


def _empty(message: str, algorithm: str = "multi_lesions") -> dict:
    algo_name = "VM-UNet 多病灶分割" if algorithm == "multi_lesions" else "CSU-EYES 微动脉瘤分割"
    counts = {"HE": 0, "EX": 0, "SE": 0} if algorithm == "multi_lesions" else {"MA": 0}
    return {
        "available": False,
        "algorithm": algorithm,
        "algorithmName": algo_name,
        "overlayUrl": "",
        "counts": counts,
        "message": message,
    }


def _allowed_urls(source) -> set[str]:
    allowed = {u for u in (source.images or []) if u}
    groups = source.image_groups or {}
    if isinstance(groups, dict):
        for urls in groups.values():
            for url in urls or []:
                if url:
                    allowed.add(url)
    return allowed


def _infer(image_path: Path, weight: Path, case_id: int) -> dict:
    global _loaded_model
    root = _vendor_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import torch
    from predict_multilesions import load_model, predict_one_image

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if _loaded_model is None:
        _loaded_model = load_model(weight, device)
    out_dir = project_root() / settings.UPLOAD_DIR / "lesion-seg" / str(case_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    summary = predict_one_image(
        image_path=image_path,
        weight_path=weight,
        output_dir=out_dir,
        device=device,
        model=_loaded_model,
        save_probabilities=False,
    )
    seconds = round(time.perf_counter() - started, 1)
    counts_raw = summary.get("pixel_counts") or {}
    counts = {
        "HE": int(counts_raw.get("HE") or 0),
        "EX": int(counts_raw.get("EX") or 0),
        "SE": int(counts_raw.get("SE") or 0),
    }
    overlay_name = f"{image_path.stem}_overlay.png"
    overlay_path = out_dir / overlay_name
    if not overlay_path.is_file():
        raise RuntimeError("分割跑完了，但没有写出叠加图")
    overlay_url = (
        f"{settings.STATIC_URL.rstrip('/')}/lesion-seg/{case_id}/{overlay_name}"
        f"?t={int(time.time())}"
    )
    parts = [f"{_LABELS[key]} {counts[key]} 像素" for key in ("HE", "EX", "SE")]
    return {
        "available": True,
        "algorithm": "multi_lesions",
        "algorithmName": "VM-UNet 多病灶分割",
        "overlayUrl": overlay_url,
        "counts": counts,
        "device": str(device),
        "seconds": seconds,
        "message": "已叠加：" + "，".join(parts) + "。红=出血，黄=硬性渗出，绿=软性渗出。",
    }


async def _predict_ma(image_path: Path, case_id: int, eye: Optional[str] = "") -> dict:
    from app.services import csu_eyes_client
    from app.common.utils import save_b64_image_to_screening

    try:
        raw = await csu_eyes_client.detect_ma(image_path=image_path)
    except HTTPException as exc:
        return {
            "available": False,
            "algorithm": "ma_detection",
            "algorithmName": "CSU-EYES 微动脉瘤分割",
            "overlayUrl": "",
            "counts": {"MA": 0},
            "seconds": 0,
            "message": f"微动脉瘤算法服务调用失败：{exc.detail}",
        }
    except Exception as exc:
        return {
            "available": False,
            "algorithm": "ma_detection",
            "algorithmName": "CSU-EYES 微动脉瘤分割",
            "overlayUrl": "",
            "counts": {"MA": 0},
            "seconds": 0,
            "message": f"微动脉瘤算法服务暂不可用：{exc}",
        }

    ma_count = int(raw.get("ma_count") or 0)
    overlay_b64 = raw.get("overlay_base64") or ""
    overlay_url = ""
    if overlay_b64:
        overlay_url = save_b64_image_to_screening(
            overlay_b64,
            prefix="ma_predict",
            case_no=str(case_id),
            suffix=(eye or "").lower(),
        )
        if not overlay_url:
            overlay_url = f"data:image/png;base64,{overlay_b64}"

    return {
        "available": True,
        "algorithm": "ma_detection",
        "algorithmName": "CSU-EYES 微动脉瘤分割",
        "overlayUrl": overlay_url,
        "counts": {"MA": ma_count},
        "seconds": float(raw.get("inference_time") or 0),
        "message": f"微动脉瘤分割完成，共检出 {ma_count} 处微动脉瘤 (MA)。洋红/品红=微动脉瘤。",
    }


class LesionSegService:
    @staticmethod
    def run(db, user: User, case_id: int, image_url: str) -> dict:
        source = ReadingService.get_image_source(db=db, user=user, case_id=case_id)
        raw = (image_url or "").strip().split("?", 1)[0]
        if raw not in _allowed_urls(source):
            raise HTTPException(status_code=400, detail="这张图不属于当前病例")
        image_path = _resolve_static_file(raw)
        if image_path is None:
            raise HTTPException(status_code=400, detail="找不到这张眼底原图的文件")

        weight = _weight_file()
        if weight is None:
            return _empty("多病灶分割已接入，但权重文件 best_mdice.pth 不在服务器上。")
        if not (_vendor_root() / "predict_multilesions.py").is_file():
            return _empty("多病灶分割已接入，但推理代码不在 backend/vendor/multi_lesions_seg。")

        try:
            return _infer(image_path, weight, case_id)
        except ModuleNotFoundError as exc:
            missing = getattr(exc, "name", None) or "依赖"
            return _empty(
                "多病灶分割已接入，当前环境还跑不起来。"
                f"缺少 {missing}。需要 PyTorch、scipy、einops、timm，"
                "以及 mamba_ssm 提供的 selective_scan（模型前向走这条路径）。"
            )
        except NameError as exc:
            if "selective_scan" in str(exc):
                return _empty(
                    "多病灶分割已接入，但 mamba_ssm 的 selective_scan 不可用。"
                    "只装 CPU 版 PyTorch 不够，模型前向需要这份算子。"
                )
            return _empty(f"多病灶分割没有完成：{exc}")
        except Exception as exc:
            return _empty(f"多病灶分割没有完成：{exc}")

    @staticmethod
    async def predict(
        db,
        user: User,
        case_id: int,
        image_url: str,
        algorithm: str = "multi_lesions",
        eye: Optional[str] = "",
    ) -> dict:
        source = ReadingService.get_image_source(db=db, user=user, case_id=case_id)
        raw = (image_url or "").strip().split("?", 1)[0]
        if raw not in _allowed_urls(source):
            raise HTTPException(status_code=400, detail="这张图不属于当前病例")
        image_path = _resolve_static_file(raw)
        if image_path is None:
            raise HTTPException(status_code=400, detail="找不到这张眼底原图的文件")

        if algorithm == "ma_detection":
            return await _predict_ma(image_path, case_id, eye)

        # multi_lesions 算法（VM-UNet）
        weight = _weight_file()
        if weight is None:
            return _empty("多病灶分割已接入，但权重文件 best_mdice.pth 不在服务器上。", algorithm="multi_lesions")
        if not (_vendor_root() / "predict_multilesions.py").is_file():
            return _empty("多病灶分割已接入，但推理代码不在 backend/vendor/multi_lesions_seg。", algorithm="multi_lesions")

        try:
            return _infer(image_path, weight, case_id)
        except ModuleNotFoundError as exc:
            missing = getattr(exc, "name", None) or "依赖"
            return _empty(
                "多病灶分割已接入，当前环境还跑不起来。"
                f"缺少 {missing}。需要 PyTorch、scipy、einops、timm，"
                "以及 mamba_ssm 提供的 selective_scan（模型前向走这条路径）。",
                algorithm="multi_lesions",
            )
        except NameError as exc:
            if "selective_scan" in str(exc):
                return _empty(
                    "多病灶分割已接入，但 mamba_ssm 的 selective_scan 不可用。"
                    "只装 CPU 版 PyTorch 不够，模型前向需要这份算子。",
                    algorithm="multi_lesions",
                )
            return _empty(f"多病灶分割没有完成：{exc}", algorithm="multi_lesions")
        except Exception as exc:
            return _empty(f"多病灶分割没有完成：{exc}", algorithm="multi_lesions")
