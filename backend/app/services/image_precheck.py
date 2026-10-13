# -*- coding: utf-8 -*-
"""
建案前的本地轻量预检。

CSU-EYES 质控模型只输出 好 / 可用 / 差，不会返回「不可判读」，
也认不出「这根本不是眼底图」。这里只拦明显坏图：
无法解码、分辨率过低、整体接近全黑或全白。
命中任一项即视为不可判读，阻止建案（可人工放行）。
阈值刻意放得很宽，宁可漏拦交给质控模型，也不误拦正常图。
"""

from pathlib import Path
from typing import Optional

MIN_SIDE_PX = 256
DARK_MEAN = 12
BRIGHT_MEAN = 243
FLAT_STDDEV = 4


def precheck(path: Path) -> Optional[str]:
    """返回不可判读原因；通过时返回 None。"""
    try:
        from PIL import Image, ImageStat

        with Image.open(path) as img:
            img.load()
            width, height = img.size
            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            mean = float(stat.mean[0])
            stddev = float(stat.stddev[0])
    except Exception:
        return "图像无法解码"

    if min(width, height) < MIN_SIDE_PX:
        return f"分辨率过低（{width}×{height}，短边需不少于 {MIN_SIDE_PX} 像素）"
    if stddev < FLAT_STDDEV:
        return "图像几乎没有内容（整幅为纯色）"
    if mean < DARK_MEAN:
        return "图像整体接近全黑"
    if mean > BRIGHT_MEAN:
        return "图像整体接近全白"
    return None


__all__ = ["precheck", "MIN_SIDE_PX"]
