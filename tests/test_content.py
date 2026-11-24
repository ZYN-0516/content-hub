"""内容接口单元测试：广场可见性、搜索、评论、我的作品隔离。"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.models import Comment, Content, ReviewTask

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def client():
    return APIClient()


def _content(author, title, status):
    return Content.objects.create(
        author=author, title=title, content_type="image", file="content/test.png",
        status=status,
    )


def test_gallery_only_published(client, member):
    pub = _content(member, "公开作品", Content.Status.PUBLISHED)
    draft = _content(member, "草稿作品", Content.Status.DRAFT)

    data = client.get("/api/content/").json()["data"]
    ids = [x["id"] for x in data]
    assert pub.id in ids and draft.id not in ids

    # 未发布作品非作者访问 404
    anon = APIClient()
    assert anon.get(f"/api/content/{draft.id}/").status_code == 404
    anon.force_authenticate(user=member)
    assert anon.get(f"/api/content/{draft.id}/").status_code == 200


def test_search_by_title(client, member):
    _content(member, "戴眼镜的橘猫", Content.Status.PUBLISHED)
    _content(member, "雪山日落", Content.Status.PUBLISHED)

    hit = client.get("/api/content/search/?q=橘猫").json()["data"]
    assert len(hit) == 1 and "橘猫" in hit[0]["title"]
    assert client.get("/api/content/search/?q=不存在").json()["data"] == []


def test_comment_list_and_create(client, member):
    content = _content(member, "作品", Content.Status.PUBLISHED)

    # 匿名只能读
    assert client.get(f"/api/comments/?content_id={content.id}").status_code == 200
    r = client.post("/api/comments/", {"content": content.id, "text": "匿名评论"}, format="json")
    assert r.status_code in (401, 403)

    client.force_authenticate(user=member)
    r = client.post("/api/comments/", {"content": content.id, "text": "很好看"}, format="json")
    assert r.status_code == 200
    data = client.get(f"/api/comments/?content_id={content.id}").json()["data"]
    assert any(x["user_name"] == member.username and x["text"] == "很好看" for x in data)


def test_mine_only_self_with_review_status(client, member, admin):
    mine = _content(member, "我的作品", Content.Status.REJECTED)
    others = _content(admin, "别人的作品", Content.Status.PUBLISHED)
    ReviewTask.objects.create(
        content=mine, status=ReviewTask.Status.REJECTED, comment="换个背景",
    )

    client.force_authenticate(user=member)
    data = client.get("/api/content/mine/").json()["data"]
    ids = [x["id"] for x in data]
    assert mine.id in ids and others.id not in ids
    item = next(x for x in data if x["id"] == mine.id)
    assert item["review_status"] == "rejected"
    assert item["review_comment"] == "换个背景"

    anon = APIClient()
    assert anon.get("/api/content/mine/").status_code == 401
