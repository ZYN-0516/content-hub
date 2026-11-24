"""pytest 共享夹具：用户工厂与 API 客户端。

所有测试运行在 config.settings.test（内存 SQLite + USE_MOCK_AI=True），
不调用百炼、不写真实 media 目录。
"""
import itertools
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

_counter = itertools.count(1)
STRONG_PASSWORD = "Xy7#Kp9@mQ"


@pytest.fixture(autouse=True)
def _isolate_media(settings, tmp_path):
    """把媒体目录指到临时目录，避免测试生成文件污染 media/。"""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.MEDIA_URL = "/media/"


@pytest.fixture
def user_factory():
    User = get_user_model()

    def make(username=None, role="member", **kwargs):
        n = next(_counter)
        username = username or f"user{n}"
        defaults = {
            "username": username,
            "email": f"user{n}_{username}@example.com",
            "password": STRONG_PASSWORD,
            "role": role,
        }
        defaults.update(kwargs)
        return User.objects.create_user(**defaults)

    return make


@pytest.fixture
def member(user_factory):
    return user_factory()


@pytest.fixture
def reviewer(user_factory):
    return user_factory(role="reviewer")


@pytest.fixture
def admin(user_factory):
    """普通管理员：role=admin，但非 staff / 非 superuser。"""
    return user_factory(role="admin")


@pytest.fixture
def superuser(user_factory):
    u = user_factory(role="member", is_staff=True, is_superuser=True)
    return u


@pytest.fixture
def api():
    return APIClient()


def auth(api, user):
    api.force_authenticate(user=user)
    return api
