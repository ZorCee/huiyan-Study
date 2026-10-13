# -*- coding: utf-8 -*-
"""第 3 项"质量"命名、第 5 项病灶颜色映射的静态检查。本对话未改动这两项，按验收标准测当前代码。

第 5 项"算法输出与金标准明显不同"需要真实的分割服务和权重，沙箱内没有，记为阻塞，不在这里测。
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FRONT = ROOT / "frontend" / "src"

QUALIFIED = ("图像质量", "影像质量", "图片质量", "画质", "标注质量", "阅片质量", "质量控制", "质控", "教学质量")


def _template_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"<template>(.*)</template>", text, re.S)
    return match.group(1) if match else ""


def test_r3_01_quality_word_always_qualified():
    """R3-01 | 界面上"质量"都带限定词
    前置: frontend/src 下全部 .vue 模板
    步骤: 扫描 <template> 中出现的"质量"，去掉已带限定词的写法
    预期: 不存在单独出现、含义不明的"质量"
    """
    loose = []
    for vue in FRONT.rglob("*.vue"):
        body = _template_text(vue)
        for line_no, line in enumerate(body.splitlines(), 1):
            stripped = line
            for word in QUALIFIED:
                stripped = stripped.replace(word, "")
            if "质量" in stripped:
                loose.append(f"{vue.relative_to(ROOT)}:{line_no}: {line.strip()[:80]}")
    assert not loose, "未带限定词的“质量”：\n" + "\n".join(loose[:30])


IDRID_KEYS = {"MA", "HE", "EX", "SE", "OD"}


def _legend():
    text = (FRONT / "views/reading/components/ReadingSidePanel.vue").read_text(encoding="utf-8")
    return dict(re.findall(r"key:\s*'(\w+)'.*?color:\s*'(#[0-9a-fA-F]{6})'", text))


def test_r5_01_legend_covers_idrid_classes():
    """R5-01 | 右侧图例覆盖 IDRiD 的 5 类病灶 / 结构
    前置: ReadingSidePanel.vue 中的图例表
    步骤: 读取图例的 key 集合
    预期: 覆盖 MA、HE、EX、SE、OD（允许临床白皮书新增的 NV）
    """
    assert IDRID_KEYS.issubset(set(_legend()))
    assert set(_legend()) - IDRID_KEYS <= {"NV"}


def test_r5_02_legend_colors_are_distinct():
    """R5-02 | 各病灶颜色互不相同
    前置: 图例表
    步骤: 比较颜色值
    预期: 5 个颜色两两不同
    """
    colors = [c.lower() for c in _legend().values()]
    assert len(colors) == len(set(colors))


@pytest.mark.parametrize("key", ["HE", "EX", "SE"])
def test_r5_03_backend_labels_match_legend(key):
    """R5-03 | 后端多病灶分割输出的类别与图例一致
    前置: lesion_seg_service.py 的类别表
    步骤: 检查 HE / EX / SE 在后端类别表和前端图例中都存在
    预期: 都存在（MA 由微动脉瘤分割单独输出）
    """
    from app.services import lesion_seg_service as seg
    assert key in seg._LABELS
    assert key in _legend()
