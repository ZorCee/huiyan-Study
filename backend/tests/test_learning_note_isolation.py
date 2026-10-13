# -*- coding: utf-8 -*-
"""「我的笔记」数据隔离：多账号交叉 + 管理员审核视图只读并留审计。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import learning as learning_api
from app.core.dependencies import require_roles
from app.db.base import Base
from app.db.models import LearningNote, Role, RoleEnum, User
from app.db.models.operation_log import OperationLog
from app.schemas.learning import NoteCreateParams, NoteListQuery, NoteUpdateParams
from app.services.learning_service import LearningService


def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _setup(db):
    roles = {
        code: Role(code=code.value, name=code.value)
        for code in (RoleEnum.STUDENT, RoleEnum.TEACHER, RoleEnum.ADMIN)
    }
    db.add_all(roles.values())
    db.flush()
    users = {
        name: User(username=name, password_hash="x", real_name=name, role_id=roles[code].id)
        for name, code in [
            ("a", RoleEnum.STUDENT), ("b", RoleEnum.STUDENT),
            ("teacher", RoleEnum.TEACHER), ("admin", RoleEnum.ADMIN),
        ]
    }
    db.add_all(users.values())
    db.commit()
    notes = {
        name: LearningService.create_note(
            db, user=u, params=NoteCreateParams(title=f"{name} 的笔记", content="内容"),
        )
        for name, u in users.items()
    }
    return users, notes


def _mine(db, user, **kw):
    return {n.id for n in LearningService.list_notes(db, user=user, query=NoteListQuery(**kw)).list}


def test_every_role_only_sees_own_notes_in_my_notes():
    db = _db()
    users, notes = _setup(db)
    for name, user in users.items():
        assert _mine(db, user) == {notes[name].id}
    db.close()


def test_admin_user_id_param_is_ignored_in_my_notes():
    db = _db()
    users, notes = _setup(db)
    assert _mine(db, users["admin"], user_id=users["a"].id) == {notes["admin"].id}
    db.close()


@pytest.mark.parametrize("actor", ["b", "teacher", "admin"])
def test_others_cannot_read_edit_or_delete(actor):
    db = _db()
    users, notes = _setup(db)
    target = notes["a"].id
    user = users[actor]
    with pytest.raises(HTTPException) as e1:
        LearningService.get_note(db, user=user, note_id=target)
    with pytest.raises(HTTPException) as e2:
        LearningService.update_note(db, user=user, note_id=target, params=NoteUpdateParams(title="改"))
    with pytest.raises(HTTPException) as e3:
        LearningService.delete_note(db, user=user, note_id=target)
    assert e1.value.status_code == e2.value.status_code == e3.value.status_code == 403
    assert db.query(LearningNote).get(target).title == "a 的笔记"
    db.close()


def test_owner_can_still_read_edit_delete():
    db = _db()
    users, notes = _setup(db)
    a, nid = users["a"], notes["a"].id
    assert LearningService.get_note(db, user=a, note_id=nid).id == nid
    assert LearningService.update_note(db, user=a, note_id=nid, params=NoteUpdateParams(title="新")).title == "新"
    LearningService.delete_note(db, user=a, note_id=nid)
    assert _mine(db, a) == set()
    db.close()


@pytest.mark.parametrize("actor", ["a", "teacher"])
def test_admin_view_rejects_non_admin(actor):
    db = _db()
    users, _ = _setup(db)
    checker = require_roles(RoleEnum.ADMIN)
    with pytest.raises(HTTPException) as e:
        checker(current_user=users[actor])
    assert e.value.status_code == 403
    db.close()


def test_admin_view_lists_others_and_writes_audit_log():
    db = _db()
    users, notes = _setup(db)
    admin = users["admin"]
    req = SimpleNamespace(client=SimpleNamespace(host="10.0.0.1"))

    learning_api.admin_list_notes(
        current_user=admin, db=db, request=req,
        keyword=None, userId=users["a"].id, caseId=None, page=1, pageSize=20,
    )
    learning_api.admin_get_note(current_user=admin, db=db, request=req, noteId=notes["b"].id)

    page = LearningService.admin_list_notes(db, query=NoteListQuery(user_id=users["a"].id))
    assert [n.id for n in page.list] == [notes["a"].id]
    assert LearningService.admin_list_notes(db, query=NoteListQuery()).total == 4

    logs = db.query(OperationLog).filter(OperationLog.module == "learning").order_by(OperationLog.id).all()
    assert [l.action for l in logs] == ["note.admin_list", "note.admin_view"]
    assert all(l.user_id == admin.id and l.ip == "10.0.0.1" for l in logs)
    assert f"#{notes['b'].id}" in logs[1].detail and "作者 b" in logs[1].detail
    db.close()
