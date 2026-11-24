"""生成任务闭环手动测试（不会被自动执行）。

用法：
    .\\venv\\Scripts\\python.exe tests\\test_task_flow.py              # 创建任务
    .\\venv\\Scripts\\python.exe tests\\test_task_flow.py <task_id>    # 查询任务状态
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402


def _admin_client() -> APIClient:
    User = get_user_model()
    admin = User.objects.filter(is_staff=True).order_by("id").first()
    if admin is None:
        raise SystemExit("未找到管理员用户，请先执行：manage.py createsuperuser")

    client = APIClient()
    client.force_authenticate(user=admin)
    return client


def create_task() -> None:
    client = _admin_client()
    payload = {"task_type": "image", "prompt": "一只在写代码的猫"}
    response = client.post("/api/generation/tasks/", payload, format="json")
    print(f"POST /api/generation/tasks/ -> HTTP {response.status_code}")
    print(f"response: {response.data}")

    data = (response.data or {}).get("data") or {}
    task_id = data.get("id")
    print(f"任务 id={task_id} status={data.get('status')}")
    print("请到 celery worker 终端查看生成日志；稍后用以下命令查询：")
    print(f"  .\\venv\\Scripts\\python.exe tests\\test_task_flow.py {task_id}")


def check_task(task_id: int) -> None:
    client = _admin_client()
    response = client.get(f"/api/generation/tasks/{task_id}/")
    print(f"GET /api/generation/tasks/{task_id}/ -> HTTP {response.status_code}")
    print(f"response: {response.data}")

    data = (response.data or {}).get("data") or {}
    print(f"当前 status: {data.get('status')}")

    content_id = (data.get("parameters") or {}).get("content_id")
    print(f"关联 content_id: {content_id}")

    if content_id:
        content_response = client.get(f"/api/content/{content_id}/")
        print(f"content: {content_response.data}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_task(int(sys.argv[1]))
    else:
        create_task()
