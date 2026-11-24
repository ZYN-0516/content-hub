"""审核闭环单元测试：提交审核、通过/驳回、角色权限边界。"""
import pytest
from rest_framework.test import APIClient

from apps.core.models import Content, ReviewTask

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


def _content(author, status=Content.Status.DRAFT, title="测试作品"):
    return Content.objects.create(
        author=author, title=title, content_type="image", file="content/test.png",
        status=status,
    )


def test_submit_review_then_approve(client, member, reviewer):
    content = _content(member)
    client.force_authenticate(user=member)
    r = client.post(f"/api/content/{content.id}/submit-review/")
    assert r.status_code == 200
    content.refresh_from_db()
    assert content.status == Content.Status.PENDING
    review = ReviewTask.objects.get(content=content)
    assert review.status == ReviewTask.Status.PENDING

    client.force_authenticate(user=reviewer)
    r = client.post(f"/api/review/tasks/{review.id}/approve/")
    assert r.status_code == 200
    content.refresh_from_db()
    review.refresh_from_db()
    assert content.status == Content.Status.PUBLISHED
    assert review.status == ReviewTask.Status.APPROVED
    assert review.reviewer_id == reviewer.id


def test_reject_then_resubmit_keeps_history(client, member, reviewer):
    content = _content(member)
    client.force_authenticate(user=member)
    client.post(f"/api/content/{content.id}/submit-review/")
    review1 = ReviewTask.objects.get(content=content)

    client.force_authenticate(user=reviewer)
    r = client.post(
        f"/api/review/tasks/{review1.id}/reject/",
        {"comment": "画面模糊"}, format="json",
    )
    assert r.status_code == 200
    content.refresh_from_db()
    assert content.status == Content.Status.REJECTED

    client.force_authenticate(user=member)
    client.post(f"/api/content/{content.id}/submit-review/")
    assert ReviewTask.objects.filter(content=content).count() == 2


def test_duplicate_submit_rejected(client, member):
    content = _content(member, status=Content.Status.PENDING)
    ReviewTask.objects.create(content=content, status=ReviewTask.Status.PENDING)
    client.force_authenticate(user=member)
    r = client.post(f"/api/content/{content.id}/submit-review/")
    assert r.status_code == 400


def test_review_list_status_all_shared(client, member, reviewer, admin):
    content = _content(member)
    ReviewTask.objects.create(
        content=content, status=ReviewTask.Status.APPROVED, reviewer=reviewer,
        comment="不错",
    )
    for user in (reviewer, admin):
        client.force_authenticate(user=user)
        data = client.get("/api/review/tasks/?status=all").json()["data"]
        assert any(
            x["status"] == "approved" and x["reviewer_name"] == reviewer.username
            and x["comment"] == "不错" for x in data
        )

    client.force_authenticate(user=member)
    assert client.get("/api/review/tasks/").status_code == 403


def test_reviewer_cannot_admin(client, member, reviewer, admin):
    content = _content(member)
    # 审核员只能审核，进不了管理后台
    client.force_authenticate(user=reviewer)
    assert client.get("/api/admin/content/").status_code == 403
    assert client.get("/api/admin/users/").status_code == 403

    # 普通管理员能改作品，但不能改角色
    client.force_authenticate(user=admin)
    assert client.get("/api/admin/content/").status_code == 200
    assert client.get("/api/admin/users/").status_code == 403


def test_superuser_can_grant_roles(client, superuser, member):
    client.force_authenticate(user=superuser)
    r = client.patch(
        f"/api/admin/users/{member.id}/role/",
        {"role": "admin"}, format="json",
    )
    assert r.status_code == 200
    member.refresh_from_db()
    assert member.role == "admin"
