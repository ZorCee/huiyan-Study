# -*- coding: utf-8 -*-
"""教师批量登记教学病例。先检查，通过的才入库为未发布草稿。

登记表字段定义、校验规则见 docs/病例登记表说明.md。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from fastapi import HTTPException, status
from PIL import Image, ImageFilter, ImageOps, ImageStat
from sqlalchemy.orm import Session

from app.common.eye_infer import resolve_static_file
from app.common.utils import project_root, screening_dir, screening_url
from app.core.config import settings
from app.db.models import TrainingCase, User
from app.db.models.user import RoleEnum

COLUMNS = [
    "登记号*",
    "标题",
    "病种",
    "难度",
    "年龄",
    "性别",
    "眼别*",
    "临床信息",
    "病人编号",
    "检查日期",
    "疾病分级",
    "分级标准",
    "标签",
    "备注",
]
_TEMPLATE_NOTE = (
    "# 说明（导入时跳过本行，可删除）：带 * 的列必填，其余列都可以留空。"
    "眼别填 右眼/左眼/双眼/左右眼，要和影像文件名一致。"
    "疾病分级填 0-4 的整数；分级标准填 IDRiD 或 国际临床分期。"
    "标签用逗号分隔。不要填写姓名、手机号、身份证号。"
)
_TEMPLATE_ROWS = [
    ["A001", "眼底教学例", "糖尿病视网膜病变", "入门", "60", "女", "右眼",
     "仅写病史，不要写姓名手机号身份证号", "P-01", "2024-03-01", "2", "IDRiD", "微动脉瘤,出血", ""],
    ["A002", "同一病人半年后", "糖尿病视网膜病变", "入门", "60", "女", "右眼",
     "", "P-01", "2024-09-01", "", "", "", ""],
]


def _build_template() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerow([_TEMPLATE_NOTE])
    writer.writerows(_TEMPLATE_ROWS)
    return buf.getvalue()


TEMPLATE = _build_template()

NAMING = (
    "影像文件名必须是「登记号_右眼」「登记号_左眼」或「登记号_双眼」，"
    "也可以用 _OD / _OS / _OU 或 _right / _left（_R / _L）。眼别列要和文件名一致。"
    "左右眼都有时，眼别填「左右眼」，并各传一张。"
    "登记表只有登记号、眼别必填，其余列可以留空；Excel 导出的 CSV（GBK 或 UTF-8）都能读。"
    "登记表不要出现姓名、手机号、身份证号。"
    "同一个病人不同时期要分成多行：登记号不同，病人编号相同，各自填写检查日期。"
    "没有日期就留空，不要编造。"
)

_EYE_WORD = {
    "右眼": "OD",
    "OD": "OD",
    "左眼": "OS",
    "OS": "OS",
    "双眼": "OU",
    "OU": "OU",
}
_EYE_TEXT = {"OD": "右眼", "OS": "左眼", "OU": "双眼"}
_BOTH = {"左右眼", "双眼都有", "OD+OS", "OS+OD"}
_CATEGORY = {
    "糖尿病视网膜病变": "DR",
    "DR": "DR",
    "正常": "NORMAL",
    "正常眼底": "NORMAL",
    "NORMAL": "NORMAL",
    "青光眼": "GLAUCOMA",
    "GLAUCOMA": "GLAUCOMA",
    "黄斑": "AMD",
    "老年性黄斑变性": "AMD",
    "AMD": "AMD",
    "高血压": "HYPERTENSION",
    "高血压眼底": "HYPERTENSION",
    "HYPERTENSION": "HYPERTENSION",
    "其他": "OTHER",
    "OTHER": "OTHER",
}
_DIFFICULTY = {
    "入门": "EASY",
    "简单": "EASY",
    "EASY": "EASY",
    "中级": "MEDIUM",
    "MEDIUM": "MEDIUM",
    "高级": "HARD",
    "HARD": "HARD",
}
_GENDER = {"男": "M", "女": "F", "未知": "U", "M": "M", "F": "F", "U": "U", "": "U"}
_GRADING_STANDARD = {
    "IDRID": "IDRiD",
    "国际临床分期": "国际临床分期",
    "国际临床分级": "国际临床分期",
    "ICDR": "国际临床分期",
}
_TAG_SPLIT = re.compile(r"[,，、;；]")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_IDCARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_FORBIDDEN_HEADER = ("姓名", "患者名", "手机", "电话", "身份证")
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_MIN_SIDE = 400
# 只拦接近一片空白的图。没有真实眼底图校准，阈值宁松勿紧。
_MIN_SHARPNESS = 2.0
_EYE_SUFFIXES = (
    ("_右眼", "OD"),
    ("_左眼", "OS"),
    ("_双眼", "OU"),
    ("_RIGHT", "OD"),
    ("_LEFT", "OS"),
    ("_OD", "OD"),
    ("_OS", "OS"),
    ("_OU", "OU"),
    ("_R", "OD"),
    ("_L", "OS"),
)
_DESCRIPTION = "批量导入的教学草稿，请补金标准后再发布。"
_REGISTER_MARK = "登记号：{register}（{eye}）"
_REGISTER_MARK_RE = re.compile(r"登记号：(.+?)（(.+?)）")


def _teacher(user: User) -> None:
    code = user.role.code if user.role else ""
    if code not in (RoleEnum.TEACHER.value, RoleEnum.ADMIN.value):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有教师可以批量导入病例")


def _stage_root() -> Path:
    path = project_root() / settings.UPLOAD_DIR / "uploads" / "case-import"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _phi(text: str) -> Optional[str]:
    if _PHONE.search(text or ""):
        return "含有手机号，患者信息还没去掉"
    if _IDCARD.search(text or ""):
        return "含有身份证号，患者信息还没去掉"
    return None


def _split_name(filename: str) -> Tuple[str, Optional[str]]:
    stem = Path(filename or "").stem
    upper = stem.upper()
    for suffix, eye in _EYE_SUFFIXES:
        if upper.endswith(suffix.upper()) and len(stem) > len(suffix):
            return stem[: -len(suffix)], eye
    return stem, None


def _eye_from_name(filename: str) -> Optional[str]:
    return _split_name(filename)[1]


def _register_from_name(filename: str) -> str:
    return _split_name(filename)[0]


def _sharpness(img: Image.Image) -> float:
    gray = img.convert("L")
    gray.thumbnail((512, 512))
    laplace = gray.filter(
        ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128)
    )
    width, height = laplace.size
    if width > 4 and height > 4:
        # PIL 的卷积在边缘一圈会产生假值，只统计内部。
        laplace = laplace.crop((2, 2, width - 2, height - 2))
    return ImageStat.Stat(laplace).var[0]


def _quality(raw: bytes) -> Optional[str]:
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img) or img
        img.load()
    except Exception:
        return "图像无法读取"
    width, height = img.size
    if min(width, height) < _MIN_SIDE:
        return f"图像过小（{width}×{height}），不足以入库"
    gray = img.convert("L")
    mean = ImageStat.Stat(gray).mean[0]
    if mean < 12:
        return "图像过暗，质量不足以入库"
    if mean > 248:
        return "图像过曝，质量不足以入库"
    if _sharpness(img) < _MIN_SHARPNESS:
        return "图像几乎没有细节（严重模糊或空白），质量不足以入库"
    return None


def _fingerprint(raw: bytes) -> Optional[str]:
    """缩小后比像素。同一张图重新编码成 webp 仍能对上库里的文件。"""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img) or img
        img = img.convert("RGB").resize((32, 32))
    except Exception:
        return None
    return hashlib.sha256(img.tobytes()).hexdigest()


def _existing_hashes(db: Session) -> Dict[str, str]:
    found: Dict[str, str] = {}
    rows = db.query(TrainingCase.id, TrainingCase.case_no, TrainingCase.image_paths).all()
    for _case_id, case_no, paths in rows:
        if not isinstance(paths, dict):
            continue
        for urls in paths.values():
            if not isinstance(urls, list):
                continue
            for url in urls:
                path = resolve_static_file(url or "")
                if path is None:
                    continue
                try:
                    digest = _fingerprint(path.read_bytes())
                except OSError:
                    continue
                if digest:
                    found.setdefault(digest, case_no)
    return found


def _existing_registers(db: Session) -> Dict[Tuple[str, str], str]:
    """只认本功能写进描述的登记号标记。早于本版本导入的病例没有标记，查不到。"""
    found: Dict[Tuple[str, str], str] = {}
    rows = (
        db.query(TrainingCase.case_no, TrainingCase.description)
        .filter(TrainingCase.description.like("%登记号：%"))
        .all()
    )
    for case_no, description in rows:
        for register, eye in _REGISTER_MARK_RE.findall(description or ""):
            found.setdefault((register, eye), case_no)
    return found


def _decode(raw: bytes) -> Tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    try:
        import charset_normalizer
        detected = charset_normalizer.from_bytes(raw).best()
        if detected and detected.encoding:
            return str(detected), detected.encoding
    except Exception:
        pass
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "登记表的编码无法识别。请在 Excel 里选择「另存为 → CSV UTF-8（逗号分隔）」后重新上传。",
    )


def _delimiter(text: str) -> str:
    first = next((line for line in text.splitlines() if line.strip()), "")
    counts = {sep: first.count(sep) for sep in (",", "\t", ";")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _header(name: str) -> str:
    return (name or "").strip().strip("\ufeff").strip("*＊").strip()


def _read_sheet(raw: bytes) -> Tuple[List[dict], dict]:
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "登记表是空的")
    text, encoding = _decode(raw)
    delimiter = _delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header_row = next(reader)
    except StopIteration:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "登记表是空的")
    headers = [_header(name) for name in header_row]
    if not any(headers):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "登记表第 1 行没有表头")
    for index, name in enumerate(headers, start=1):
        if any(word in name for word in _FORBIDDEN_HEADER):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"登记表第 1 行第 {index} 列「{name}」不能出现。患者信息要先去掉，只保留登记号和教学信息。",
            )
    missing = [name for name in ("登记号", "眼别") if name not in headers]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"登记表第 1 行缺少必填列：{'、'.join(missing)}",
        )
    rows: List[dict] = []
    filled: Set[str] = set()
    for cells in reader:
        line = reader.line_num
        values = {}
        for index, name in enumerate(headers):
            if not name:
                continue
            values[name] = (cells[index] if index < len(cells) else "").strip()
        if not any(values.values()):
            continue
        if values.get("登记号", "").startswith("#"):
            continue
        for name, value in values.items():
            if value:
                filled.add(name)
        values["_line"] = line
        rows.append(values)
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "登记表没有可导入的行")
    empty_columns = [name for name in headers if name and name not in filled]
    return rows, {"encoding": encoding, "delimiter": delimiter, "emptyColumns": empty_columns}


def _save_webp(raw: bytes, user_id: int) -> str:
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img) or img
    max_side = 2048
    if max(img.size) > max_side:
        ratio = max_side / max(img.size)
        img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    save_name = f"f{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.webp"
    path = screening_dir() / save_name
    img.save(path, format="WEBP", quality=90, method=6)
    return screening_url(save_name)


def _teaching_notes(standard: str, tags: List[str], remark: str) -> str:
    parts = []
    if standard:
        parts.append(f"分级标准：{standard}")
    if tags:
        parts.append(f"标签：{'、'.join(tags)}")
    if remark:
        parts.append(f"备注：{remark}")
    return "；".join(parts)


class CaseImportService:

    @staticmethod
    def require_teacher(user: User) -> None:
        _teacher(user)

    @staticmethod
    def template() -> str:
        return TEMPLATE

    @staticmethod
    def check(db: Session, user: User, sheet: bytes, files: List[tuple]) -> dict:
        _teacher(user)
        try:
            return CaseImportService._check(db, user, sheet, files)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"入库前检查没能完成：{exc}。请确认登记表是 CSV 文件、影像是常见图片格式。",
            )

    @staticmethod
    def _check(db: Session, user: User, sheet: bytes, files: List[tuple]) -> dict:
        rows, meta = _read_sheet(sheet)
        known = _existing_hashes(db)
        known_registers = _existing_registers(db)
        grouped: Dict[str, List[dict]] = {}
        by_stem: Dict[str, List[dict]] = {}
        for filename, raw in files:
            suffix = Path(filename).suffix.lower()
            if suffix not in _IMAGE_EXT:
                continue
            register, eye = _split_name(filename)
            image = {
                "filename": filename,
                "raw": raw,
                "eye": eye,
                "digest": _fingerprint(raw),
            }
            grouped.setdefault(register, []).append(image)
            # 公开数据集常把眼别写进登记号本身，如登记号 13_left 对应 13_left.jpg。
            by_stem.setdefault(Path(filename).stem, []).append(image)

        register_rows: Dict[str, int] = {}
        for row in rows:
            register = row.get("登记号") or ""
            if register:
                register_rows[register] = register_rows.get(register, 0) + 1

        seen_key: Dict[Tuple[str, str], int] = {}
        seen_digest: Dict[str, str] = {}
        report = []
        staged = []
        for row in rows:
            line = row["_line"]
            register = row.get("登记号") or ""
            eye_text = row.get("眼别") or ""
            issues: List[str] = []

            def issue(column: str, message: str) -> None:
                issues.append(f"第{line}行「{column}」：{message}")

            if not register:
                issue("登记号", "必填，不能为空")
            if not eye_text:
                issue("眼别", "必填，不能为空")

            for column, value in row.items():
                if column.startswith("_") or not value:
                    continue
                phi = _phi(value)
                if phi:
                    issue(column, phi)

            exam_on = row.get("检查日期") or ""
            if exam_on:
                try:
                    datetime.strptime(exam_on, "%Y-%m-%d")
                except ValueError:
                    issue("检查日期", "请写成 2024-03-01。没有日期就留空，不要编造")

            age_text = row.get("年龄") or ""
            if age_text and not (age_text.isdigit() and 0 <= int(age_text) <= 120):
                issue("年龄", "请填 0-120 的整数，或留空")

            grade = row.get("疾病分级") or ""
            if grade and not re.fullmatch(r"[0-4]", grade):
                issue("疾病分级", f"「{grade}」不合法，请填 0-4 的整数，或留空")

            standard_text = row.get("分级标准") or ""
            standard = _GRADING_STANDARD.get(standard_text.upper(), "")
            if standard_text and not standard:
                issue("分级标准", f"「{standard_text}」不合法，请填 IDRiD 或 国际临床分期，或留空")

            both = eye_text in _BOTH
            wanted = _EYE_WORD.get(eye_text.upper()) if eye_text else None
            if eye_text and not both and wanted is None:
                issue("眼别", f"「{eye_text}」不合法，请填右眼、左眼、双眼或左右眼")

            if register and eye_text:
                key = (register, eye_text)
                if key in seen_key:
                    issue("登记号", f"登记号 + 眼别和第{seen_key[key]}行重复")
                else:
                    seen_key[key] = line
                library_eyes = ("右眼", "左眼") if both else (_EYE_TEXT.get(wanted or "", eye_text),)
                for eye_word in library_eyes:
                    case_no = known_registers.get((register, eye_word))
                    if case_no:
                        issue("登记号", f"{register}（{eye_word}）已在病例库中（{case_no}）")

            images = list(grouped.get(register) or by_stem.get(register) or []) if register else []
            if register_rows.get(register, 0) > 1:
                accept = {"OD", "OS"} if both else {wanted}
                images = [image for image in images if image["eye"] in accept]
            if register and not images:
                issue("影像", "没有找到对应影像。文件名要用登记号加眼别，如 A001_右眼.jpg")

            eyes = []
            for image in images:
                name = image["filename"]
                if image["eye"] is None:
                    issue("影像", f"{name} 没有按命名标明左右眼")
                    continue
                if not both and wanted and image["eye"] != wanted:
                    issue("眼别", f"{name} 的眼别和登记表不一致")
                if both and image["eye"] not in ("OD", "OS"):
                    issue("影像", f"{name} 左右眼病例请分别用右眼和左眼")
                name_phi = _phi(name)
                if name_phi:
                    issue("影像", f"{name} {name_phi}")
                quality = _quality(image["raw"])
                if quality:
                    issue("影像", f"{name} {quality}")
                if image["digest"]:
                    previous = seen_digest.get(image["digest"]) or known.get(image["digest"])
                    if previous:
                        issue("影像", f"{name} 与已有影像重复（{previous}）")
                    seen_digest[image["digest"]] = register
                eyes.append(image["eye"])
            if both and images and not ({"OD", "OS"} <= set(eyes)):
                issue("影像", "眼别填了左右眼，但右眼或左眼影像不齐")

            ok = not issues
            report.append({
                "line": line,
                "registerNo": register,
                "title": row.get("标题") or "",
                "eyes": eyes,
                "ok": ok,
                "issues": issues,
            })
            if ok:
                tags = [t.strip() for t in _TAG_SPLIT.split(row.get("标签") or "") if t.strip()]
                staged.append({
                    "register_no": register,
                    "eye_text": eye_text,
                    "title": (row.get("标题") or register)[:128],
                    "category": _CATEGORY.get(row.get("病种") or "", "OTHER"),
                    "difficulty": _DIFFICULTY.get(row.get("难度") or "", "EASY"),
                    "age": age_text,
                    "gender": _GENDER.get(row.get("性别") or "", "U"),
                    "clinical": (row.get("临床信息") or "")[:2000],
                    "subject_no": (row.get("病人编号") or "")[:32],
                    "exam_on": exam_on,
                    "grade": grade,
                    "notes": _teaching_notes(standard, tags, (row.get("备注") or "")[:1000]),
                    "files": [
                        {"eye": image["eye"], "raw": image["raw"]}
                        for image in images
                        if image["eye"]
                    ],
                })

        token = ""
        if staged:
            token = uuid.uuid4().hex
            folder = _stage_root() / token
            folder.mkdir(parents=True, exist_ok=True)
            manifest_rows = []
            for index, item in enumerate(staged):
                saved = []
                for file_index, image in enumerate(item["files"]):
                    name = f"{index}_{file_index}.bin"
                    (folder / name).write_bytes(image["raw"])
                    saved.append({"eye": image["eye"], "file": name})
                manifest_rows.append({**{k: v for k, v in item.items() if k != "files"}, "files": saved})
            (folder / "manifest.json").write_text(
                json.dumps({"user_id": user.id, "rows": manifest_rows}, ensure_ascii=False),
                encoding="utf-8",
            )
        return {
            "token": token,
            "naming": NAMING,
            "total": len(report),
            "passed": sum(1 for item in report if item["ok"]),
            "failed": sum(1 for item in report if not item["ok"]),
            "rows": report,
            **meta,
        }

    @staticmethod
    def commit(db: Session, user: User, token: str) -> dict:
        _teacher(user)
        folder = _stage_root() / (token or "").strip()
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "检查结果已失效，请重新上传")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("user_id") != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "不能提交别人的导入")
        from sqlalchemy import func
        year = datetime.now().strftime("%Y")
        prefix = f"T{year}"
        count = (
            db.query(func.count(TrainingCase.id))
            .filter(TrainingCase.case_no.like(f"{prefix}%"))
            .scalar()
        ) or 0
        created = []
        written: List[str] = []
        try:
            for offset, item in enumerate(manifest.get("rows") or [], start=1):
                paths: Dict[str, List[str]] = {}
                for image in item.get("files") or []:
                    raw = (folder / image["file"]).read_bytes()
                    url = _save_webp(raw, user.id)
                    written.append(url)
                    paths.setdefault(image["eye"], []).append(url)
                age_text = str(item.get("age") or "").strip()
                age = int(age_text) if age_text.isdigit() else None
                case_no = f"{prefix}{count + offset:03d}"
                register = item.get("register_no") or ""
                eye_text = item.get("eye_text") or ""
                marks = [
                    _REGISTER_MARK.format(register=register, eye=word)
                    for word in (("右眼", "左眼") if eye_text in _BOTH else (eye_text,))
                ] if register and eye_text else []
                case = TrainingCase(
                    case_no=case_no,
                    title=item.get("title") or register or case_no,
                    description=_DESCRIPTION + "".join(marks),
                    category=item.get("category") or "OTHER",
                    difficulty=item.get("difficulty") or "EASY",
                    patient_name="",
                    patient_age=age,
                    patient_gender=item.get("gender") or "U",
                    patient_phone="",
                    subject_no=(item.get("subject_no") or "")[:32],
                    exam_on=item.get("exam_on") or "",
                    clinical_info=item.get("clinical") or "",
                    image_paths=paths,
                    gold_dr_grade=item.get("grade") or "",
                    gold_diagnosis="",
                    teaching_points=item.get("notes") or "",
                    is_published=False,
                    is_train_case=False,
                    creator_id=user.id,
                )
                db.add(case)
                db.flush()
                created.append({"id": case.id, "caseNo": case.case_no, "title": case.title})
            db.commit()
        except Exception as exc:
            db.rollback()
            for url in written:
                (screening_dir() / url.rsplit("/", 1)[-1]).unlink(missing_ok=True)
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"导入失败，本批病例全部未导入（已回滚）：{exc}。检查结果仍保留，可以直接重试。",
            )
        for child in folder.glob("*"):
            child.unlink(missing_ok=True)
        folder.rmdir()
        return {"created": created, "count": len(created)}
