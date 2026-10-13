"""AI算法判读：目录、角色可见性、颜色表前后端一致。不访问远程算法服务器。"""

import re
from pathlib import Path
from types import SimpleNamespace

from app.db.models.user import RoleEnum
from app.services import ai_algorithm_service as svc

FRONTEND_COLORS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "lesion-colors.ts"


def _user(role: str):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def test_catalog_has_all_four_algorithms():
    keys = {item["key"] for item in svc.CATALOG}
    assert keys == {"multi_lesion", "ma_detection", "ocod", "glaucoma"}
    for item in svc.CATALOG:
        for field in ("name", "kind", "model", "endpoint", "input", "output", "dependency"):
            assert item[field], f"{item['key']} 缺少 {field}"


def test_glaucoma_hidden_from_students():
    student_keys = {i["key"] for i in svc._visible(_user(RoleEnum.STUDENT.value))}
    teacher_keys = {i["key"] for i in svc._visible(_user(RoleEnum.TEACHER.value))}
    assert "glaucoma" not in student_keys
    assert "glaucoma" in teacher_keys


def test_lesion_labels_have_colors():
    for item in svc.CATALOG:
        for label in item.get("labels", []):
            assert label in svc.LESION_COLORS, f"{label} 没有颜色"


def test_lesion_colors_match_frontend():
    text = FRONTEND_COLORS.read_text(encoding="utf-8")
    pairs = dict(re.findall(r"key:\s*'(\w+)'.*?color:\s*'(#[0-9a-fA-F]{6})'", text))
    assert {k: v.lower() for k, v in pairs.items()} == {
        k: v.lower() for k, v in svc.LESION_COLORS.items()
    }
