# -*- coding: utf-8 -*-
"""
存量清理：列出（并可选重置）正式考试里被系统补交的「超时未作答」空白卷

背景：学员进入正式考试后没作答就离开，到时间被系统自动交卷，
页面显示「已交卷」且无法再进入。判定规则与 ExamService 完全一致
（app.services.exam_service.is_blank_auto_hand_in）：
    1. 该学员这场考试的所有题都已不是草稿；
    2. 没有任何一题是学员自己交的（hand_in_reason != 'MANUAL'）；
    3. 每一题都没有任何作答内容。

只处理还在进行中（OPEN）的考试；已收卷的考试成绩要留档，不动。

用法：
    # 预演（默认，只列清单，不写库）
    python scripts/reset_blank_exam_attempts.py

    # 只看某一场考试
    python scripts/reset_blank_exam_attempts.py --paper 12

    # 实际重置（删除这些空白卷记录，学员可重新进入）
    python scripts/reset_blank_exam_attempts.py --apply

    # 指定数据库（默认取 app.core.config 的配置）
    python scripts/reset_blank_exam_attempts.py --db sqlite:///edu_eye.db
"""

import argparse
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import ExamPaper, PracticeSession, User  # noqa: E402
from app.services.exam_service import is_blank_auto_hand_in  # noqa: E402


def build_session(db_url: str):
    engine = create_engine(db_url, future=True)
    return sessionmaker(bind=engine, autoflush=False, future=True)()


def resolve_db_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    try:
        from app.core.config import settings
        url = getattr(settings, "DATABASE_URL", "") or getattr(settings, "SQLALCHEMY_DATABASE_URI", "")
        if url:
            return str(url)
    except Exception:
        pass
    default_path = Path(__file__).resolve().parent.parent / "edu_eye.db"
    return f"sqlite:///{default_path.as_posix()}"


def find_blank_attempts(db, paper_id: int = 0):
    query = db.query(ExamPaper).filter(ExamPaper.status == "OPEN")
    if paper_id:
        query = query.filter(ExamPaper.id == paper_id)
    found = []
    for paper in query.order_by(ExamPaper.id.asc()).all():
        rows = (
            db.query(PracticeSession)
            .filter(PracticeSession.exam_paper_id == paper.id)
            .all()
        )
        by_user: dict = {}
        for row in rows:
            by_user.setdefault(row.user_id, []).append(row)
        for user_id, mine in sorted(by_user.items()):
            if is_blank_auto_hand_in(mine):
                found.append((paper, user_id, mine))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="列出 / 重置正式考试中超时未作答的空白卷")
    parser.add_argument("--apply", action="store_true", help="实际删除空白卷记录；不加则仅预演")
    parser.add_argument("--paper", type=int, default=0, help="只处理指定考试 ID（可选）")
    parser.add_argument("--db", default="", help="数据库连接串（可选）")
    args = parser.parse_args()

    db_url = resolve_db_url(args.db)
    db = build_session(db_url)
    print(f"数据库：{db_url}")
    print(f"模式：{'实际重置' if args.apply else '预演（不写库）'}")

    try:
        found = find_blank_attempts(db, args.paper)
        if not found:
            print("没有找到超时未作答的空白卷。")
            return 0

        names = {
            user.id: (user.real_name or user.username or "")
            for user in db.query(User).filter(User.id.in_({item[1] for item in found})).all()
        }
        print(f"\n共 {len(found)} 份空白卷：")
        print(f"{'考试ID':<8}{'考试':<20}{'学员ID':<8}{'学员':<14}{'题数':<6}记录ID")
        for paper, user_id, rows in found:
            print(
                f"{paper.id:<8}{(paper.title or '')[:18]:<20}{user_id:<8}"
                f"{names.get(user_id, f'学员{user_id}')[:12]:<14}{len(rows):<6}"
                f"{[row.id for row in rows]}"
            )

        if not args.apply:
            print("\n预演结束，未改动数据库。确认无误后加 --apply 执行。")
            return 0

        removed = 0
        for _paper, _user_id, rows in found:
            for row in rows:
                db.delete(row)
                removed += 1
        db.commit()
        print(f"\n已重置 {len(found)} 份空白卷，删除 {removed} 条记录。学员可以重新进入考试。")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"出错，已回滚：{exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
