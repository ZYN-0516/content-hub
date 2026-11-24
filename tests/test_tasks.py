"""生成任务单元测试：归属隔离、取消中止（含优化故事的可量化证据）。"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.models import Content, GenerationTask, ReviewTask

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def client():
    return APIClient()


def _make_task(user, status=GenerationTask.Status.PENDING, **params):
    return GenerationTask.objects.create(
        user=user,
        task_type="image",
        prompt="一只写代码的猫",
        status=status,
        parameters=params,
    )


def test_task_list_only_own(client, member, admin):
    own = _make_task(member)
    other = _make_task(admin)

    client.force_authenticate(user=member)
    data = client.get("/api/generation/tasks/").json()["data"]
    ids = [x["id"] for x in data]
    assert own.id in ids and other.id not in ids

    # 管理员同样只能看到自己的任务
    client.force_authenticate(user=admin)
    data = client.get("/api/generation/tasks/").json()["data"]
    ids = [x["id"] for x in data]
    assert other.id in ids and own.id not in ids


def test_task_detail_and_cancel_others_404(client, member, admin):
    other = _make_task(admin)
    client.force_authenticate(user=member)
    assert client.get(f"/api/generation/tasks/{other.id}/").status_code == 404
    assert client.post(f"/api/generation/tasks/{other.id}/cancel/").status_code == 404


def test_cancel_marks_cancelled_and_revokes(client, member):
    task = _make_task(member, celery_task_id="gen-task-test")
    client.force_authenticate(user=member)

    with patch("apps.core.views.celery_app.control.revoke") as revoke:
        r = client.post(f"/api/generation/tasks/{task.id}/cancel/")

    assert r.status_code == 200
    revoke.assert_called_once()
    task.refresh_from_db()
    assert task.status == GenerationTask.Status.FAILED
    assert task.parameters["cancelled"] is True


def test_cancel_already_finished_rejected(client, member):
    task = _make_task(member, status=GenerationTask.Status.SUCCESS)
    client.force_authenticate(user=member)
    r = client.post(f"/api/generation/tasks/{task.id}/cancel/")
    assert r.status_code == 400


def test_cancelled_task_does_not_call_ai_or_create_content(client, member):
    """优化故事：取消后 worker 不调用 AI、不落库、不覆盖状态。

    取消接口会把状态置为 failed，worker 在入口的状态检查处即早退；
    这本身就不调用 AI、不落库、不覆盖状态。
    """
    task = _make_task(member, celery_task_id="gen-task-cancel-story")
    client.force_authenticate(user=member)
    client.post(f"/api/generation/tasks/{task.id}/cancel/")

    from apps.core.tasks import generate_task

    with patch("apps.core.tasks.generate_image") as gen, \
         patch("apps.core.tasks.download_image") as dl:
        result = generate_task(task.id)

    assert result["status"] == GenerationTask.Status.FAILED
    gen.assert_not_called()
    dl.assert_not_called()
    assert Content.objects.filter(task=task).count() == 0
    task.refresh_from_db()
    assert task.status == GenerationTask.Status.FAILED  # 未被覆盖回 success


def test_optimization_before_after_cancelled_task(member):
    """优化故事量化对照：关闭取消检查（优化前）vs 保留检查（优化后）。

    优化前代码：取消只改数据库状态，worker 不检查取消标记，继续调用 AI 并落库，
    最后把状态覆盖回 success —— 用户已取消的作品仍会生成并出现在系统里。
    """
    from apps.core.tasks import generate_task

    # ---- 优化前：模拟 worker 不检查取消标记（把 _is_cancelled 恒为 False）----
    before = _make_task(member, cancelled=True, celery_task_id="gen-task-before")
    with patch("apps.core.tasks._is_cancelled", return_value=False), \
         patch("apps.core.tasks.generate_image", return_value="/media/content/x.png") as gen_before, \
         patch("apps.core.tasks.download_image", return_value="/media/content/x.png") as dl_before:
        before_result = generate_task(before.id)

    before_ai_calls = gen_before.call_count
    before_content_count = Content.objects.filter(task=before).count()
    before.refresh_from_db()

    # ---- 优化后：三处检查生效 ----
    after = _make_task(member, cancelled=True, celery_task_id="gen-task-after")
    with patch("apps.core.tasks.generate_image") as gen_after, \
         patch("apps.core.tasks.download_image") as dl_after:
        after_result = generate_task(after.id)

    after_ai_calls = gen_after.call_count
    after_content_count = Content.objects.filter(task=after).count()
    after.refresh_from_db()

    # 优化前：AI 被调用、内容落库、状态被覆盖回 success（错误行为）
    assert before_result["status"] == GenerationTask.Status.SUCCESS
    assert before_ai_calls == 1
    assert dl_before.call_count == 1
    assert before_content_count == 1
    assert before.status == GenerationTask.Status.SUCCESS

    # 优化后：AI 零调用、内容零落库、状态保持 failed（正确行为）
    assert after_result["cancelled"] is True
    assert after_ai_calls == 0
    assert dl_after.call_count == 0
    assert after_content_count == 0
    assert after.status == GenerationTask.Status.FAILED


def test_worker_honours_cancel_mark_even_if_status_pending(member):
    """竞态场景：worker 已取到 pending 任务，但取消标记已写入，三处检查仍拦住落库。"""
    task = _make_task(member, cancelled=True, celery_task_id="gen-task-race")
    from apps.core.tasks import generate_task

    with patch("apps.core.tasks.generate_image") as gen, \
         patch("apps.core.tasks.download_image") as dl:
        result = generate_task(task.id)

    assert result["cancelled"] is True
    gen.assert_not_called()
    dl.assert_not_called()
    assert Content.objects.filter(task=task).count() == 0


def test_generate_task_success_with_mock_ai(member):
    """完整闭环：Mock 模式下生成任务成功并落库 Content。"""
    from apps.core.tasks import generate_task

    task = _make_task(member)
    result = generate_task(task.id)

    assert result["status"] == GenerationTask.Status.SUCCESS
    content = Content.objects.get(task=task)
    assert content.status == Content.Status.DRAFT
    assert content.author_id == member.id
    assert content.title == "一只写代码的猫"


def test_video_task_placeholder_failed(member):
    from apps.core.tasks import generate_task

    task = GenerationTask.objects.create(
        user=member, task_type="video", prompt="测试视频",
        status=GenerationTask.Status.PENDING,
    )
    result = generate_task(task.id)
    assert result["status"] == GenerationTask.Status.FAILED
    task.refresh_from_db()
    assert "视频生成开发中" in task.parameters["error"]
