"""用户认证单元测试：注册正则、登录、用户字段。"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def client():
    return APIClient()


def test_register_success(client):
    r = client.post("/api/users/register/", {
        "username": "Tom123",
        "email": "tom@example.com",
        "password": "Xy7#Kp9@mQ",
    }, format="json")
    assert r.status_code == 200
    assert User.objects.filter(username="Tom123").exists()


@pytest.mark.parametrize("username,email,password", [
    ("1abc", "a1@example.com", "Xy7#Kp9@mQ"),      # 账号数字开头
    ("ab", "a2@example.com", "Xy7#Kp9@mQ"),        # 账号太短
    ("a b c", "a3@example.com", "Xy7#Kp9@mQ"),     # 账号含空格
    ("Alice1", "a4@example.com", "onlyletters"),    # 密码无数字
    ("Bob123", "a5@example.com", "12345678"),       # 密码无字母
])
def test_register_invalid_regex_rejected(client, username, email, password):
    r = client.post("/api/users/register/", {
        "username": username, "email": email, "password": password,
    }, format="json")
    assert r.status_code == 400
    assert not User.objects.filter(username=username).exists()


def test_register_duplicate_username_rejected(client, member):
    r = client.post("/api/users/register/", {
        "username": member.username,
        "email": "dup@example.com",
        "password": "Xy7#Kp9@mQ",
    }, format="json")
    assert r.status_code == 400


def test_login_success_and_me_fields(client, member):
    from apps.users.serializers import UserSerializer

    # member 夹具的密码由工厂设置；直接调登录需知道密码，故用 force 校验 me 字段
    client.force_authenticate(user=member)
    me = client.get("/api/users/me/")
    assert me.status_code == 200
    data = me.json()["data"]
    assert "role" in data and "is_staff" in data and "is_superuser" in data
    assert UserSerializer(member).data["username"] == member.username


def test_login_with_username_or_email(client):
    User.objects.create_user(
        username="LoginUser", email="login@example.com", password="Xy7#Kp9@mQ"
    )
    for identifier in ("LoginUser", "login@example.com"):
        r = client.post("/api/users/login/", {
            "username": identifier, "password": "Xy7#Kp9@mQ",
        }, format="json")
        assert r.status_code == 200
        assert "access" in r.json()["data"]
