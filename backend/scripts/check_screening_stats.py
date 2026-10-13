# -*- coding: utf-8 -*-
"""
筛查统计体检（只读）

AI 筛查页顶部统计的口径（与 ScreeningService.stats(scope=None) 一致）：
    累计筛查 = biz_screening_case 全部记录数（按次数，不去重）
    高危/中危/正常 = 每个病例取 biz_screening_result.risk_level 最高等级，各计一次
    分析中/排队 = status IN (PENDING, PROCESSING)

本脚本：
    1. 列出卡在 PROCESSING 超过 N 分钟（默认 10）或状态为 FAILED 的记录；
    2. 用独立的 SQL 重新数一遍，与 ScreeningService.stats() 的返回值逐项核对。

脚本不修改任何数据。卡住的记录如何处理需人工确认后另行执行。

用法：
    python scripts/check_screening_stats.py
    python scripts/check_screening_stats.py --stuck-minutes 30
    python scripts/check_screening_stats.py --export stuck.csv   # 同时导出 CSV 备份
"""

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.models  # noqa: E402,F401
from app.db.models import ScreeningCase, ScreeningResult  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.screening_service import ScreeningService  # noqa: E402

RISK_RANK = {"URGENT": 3, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
RANK_KEY = {3: "red", 2: "yellow", 1: "green"}


def collect_suspicious(db, stuck_minutes: int):
    cutoff = datetime.now() - timedelta(minutes=stuck_minutes)
    rows = (
        db.query(ScreeningCase)
        .filter(
            (ScreeningCase.status == "FAILED")
            | ((ScreeningCase.status == "PROCESSING") & (ScreeningCase.created_at < cutoff))
        )
        .order_by(ScreeningCase.id)
        .all()
    )
    return [
        {
            "id": c.id,
            "case_no": c.case_no,
            "status": c.status,
            "created_at": c.created_at.isoformat(sep=" ") if c.created_at else "",
            "remark": (c.remark or "")[:80],
            "reason": "FAILED" if c.status == "FAILED" else f"PROCESSING > {stuck_minutes} 分钟",
        }
        for c in rows
    ]


def recount(db):
    statuses = Counter(s for (s,) in db.query(ScreeningCase.status).all())
    best: dict = {}
    for case_id, level in db.query(ScreeningResult.case_id, ScreeningResult.risk_level).all():
        rank = RISK_RANK.get(level or "", 0)
        best[case_id] = max(best.get(case_id, 0), rank)
    risk = Counter(RANK_KEY[r] for r in best.values() if r in RANK_KEY)
    return {
        "total": sum(statuses.values()),
        "red": risk["red"],
        "yellow": risk["yellow"],
        "green": risk["green"],
        "pending": statuses["PENDING"] + statuses["PROCESSING"],
        "failed": statuses["FAILED"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="筛查统计体检（只读）")
    parser.add_argument("--stuck-minutes", type=int, default=10)
    parser.add_argument("--export", metavar="CSV", help="把可疑记录导出为 CSV 备份")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        suspicious = collect_suspicious(db, args.stuck_minutes)
        expected = recount(db)
        actual = ScreeningService.stats(db=db, scope=None).model_dump()
    finally:
        db.close()

    print(f"== 可疑记录：{len(suspicious)} 条 ==")
    for r in suspicious:
        print(f"  #{r['id']:<6} {r['case_no']:<12} {r['status']:<10} {r['created_at']}  {r['reason']}")

    print("\n== 统计核对（独立重算 vs 接口返回）==")
    mismatched = 0
    for key, value in expected.items():
        got = actual.get(key)
        flag = "OK" if got == value else "不一致"
        if got != value:
            mismatched += 1
        print(f"  {key:<8} 重算={value:<6} 接口={got:<6} {flag}")

    if args.export:
        with open(args.export, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=["id", "case_no", "status", "created_at", "remark", "reason"]
            )
            writer.writeheader()
            writer.writerows(suspicious)
        print(f"\n已导出 {len(suspicious)} 条到 {args.export}")

    print("\n本脚本未修改任何数据。")
    return 1 if mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
