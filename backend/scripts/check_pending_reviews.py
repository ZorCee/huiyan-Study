# -*- coding: utf-8 -*-
"""
待批阅记录体检（只读）

「作业批阅」角标与列表的统计口径：biz_reading_annotation.status = 'SUBMITTED'。
本脚本列出这些记录里可能属于异常数据的条目，帮助判断角标数字是否被脏数据撑高：
    - 病例已归档（archive_status = ARCHIVED）
    - 病例未发布 / 已移出实训库
    - 学员账号已停用（is_active = False）

脚本不修改任何数据。处理方式需人工确认后另行执行。

用法：
    python scripts/check_pending_reviews.py              # 只打印
    python scripts/check_pending_reviews.py --export x.csv  # 同时导出 CSV 备份
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.models  # noqa: E402,F401
from app.db.models import ReadingAnnotation, TrainingCase, User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

PENDING_STATUS = "SUBMITTED"


def collect(db):
    rows = (
        db.query(ReadingAnnotation, TrainingCase, User)
        .outerjoin(TrainingCase, TrainingCase.id == ReadingAnnotation.case_id)
        .outerjoin(User, User.id == ReadingAnnotation.user_id)
        .filter(ReadingAnnotation.status == PENDING_STATUS)
        .order_by(ReadingAnnotation.id)
        .all()
    )
    total = len(rows)
    suspicious = []
    for record, case, user in rows:
        reasons = []
        if case is None:
            reasons.append("病例不存在")
        else:
            if case.archive_status == "ARCHIVED":
                reasons.append("病例已归档")
            if not case.is_published or not case.is_train_case:
                reasons.append("病例未发布或不在实训库")
        if user is None:
            reasons.append("学员不存在")
        elif not user.is_active:
            reasons.append("学员账号已停用")
        if reasons:
            suspicious.append({
                "record_id": record.id,
                "record_kind": record.record_kind,
                "case_id": record.case_id,
                "case_no": getattr(case, "case_no", ""),
                "user_id": record.user_id,
                "user_name": getattr(user, "real_name", "") or getattr(user, "username", ""),
                "reasons": "；".join(reasons),
            })
    return total, suspicious


def main():
    parser = argparse.ArgumentParser(description="待批阅记录体检（只读）")
    parser.add_argument("--export", metavar="CSV", help="把可疑记录导出到 CSV 备份")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total, suspicious = collect(db)
    finally:
        db.close()

    print(f"待批阅（status={PENDING_STATUS}）共 {total} 条，其中可疑 {len(suspicious)} 条。")
    for row in suspicious:
        print(
            f"  #{row['record_id']} [{row['record_kind']}] 病例 {row['case_no'] or row['case_id']}"
            f" / 学员 {row['user_name'] or row['user_id']}：{row['reasons']}"
        )

    if args.export and suspicious:
        with open(args.export, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(suspicious[0].keys()))
            writer.writeheader()
            writer.writerows(suspicious)
        print(f"已导出到 {args.export}")


if __name__ == "__main__":
    main()
