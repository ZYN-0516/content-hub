"""AI service 层单元测试：全部 mock，不产生任何百炼调用与费用。"""
from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from apps.core import services
from apps.core.services import AIServiceError

pytestmark = pytest.mark.django_db


def test_size_normalization_x_to_star():
    """优化故事：1024x1024 会被服务端拒绝，提交前统一转成 1024*1024。"""
    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "output": {
            "task_id": "dashscope-task-1",
            "task_status": "SUCCEEDED",
            "results": [{"url": "https://example.com/a.png"}],
        }
    }

    with override_settings(
        USE_MOCK_AI=False,
        DASHSCOPE_API_KEY="test-key",
        DASHSCOPE_IMAGE_API_BASE="https://example.com",
        DASHSCOPE_IMAGE_MODEL="wanx2.1-t2i-turbo",
    ), patch.object(services.requests, "post", return_value=fake_response) as post:
        url = services.generate_image("测试", size="1024x1024")

    assert url == "https://example.com/a.png"
    payload = post.call_args.kwargs["json"]
    assert payload["parameters"]["size"] == "1024*1024"


def test_text_chat_mock_mode_no_network():
    with override_settings(USE_MOCK_AI=True):
        assert services.text_chat("你好").startswith("MOCK:")
    with patch.object(services.requests, "post") as post:
        with override_settings(USE_MOCK_AI=True):
            services.text_chat("你好")
        post.assert_not_called()


def test_text_chat_missing_key_raises():
    from django.conf import settings

    with override_settings(USE_MOCK_AI=False, DASHSCOPE_API_KEY=""):
        with pytest.raises(AIServiceError, match="DASHSCOPE_API_KEY"):
            services.text_chat("你好")


def test_text_chat_http_error_wrapped():
    bad = Mock(status_code=401, text="unauthorized")
    with override_settings(
        USE_MOCK_AI=False, DASHSCOPE_API_KEY="k",
        DASHSCOPE_BASE_URL="https://example.com/v1",
    ), patch.object(services.requests, "post", return_value=bad):
        with pytest.raises(AIServiceError, match="文本生成失败"):
            services.text_chat("你好")


def test_image_missing_key_raises():
    with override_settings(USE_MOCK_AI=False, DASHSCOPE_API_KEY=""):
        with pytest.raises(AIServiceError, match="DASHSCOPE_API_KEY"):
            services.generate_image("测试", size="1024*1024")


def test_extract_image_url_no_result_raises():
    with pytest.raises(AIServiceError, match="无可用结果"):
        services._extract_image_url({"message": "无结果"}, "task-x")


def test_download_local_url_is_noop():
    with patch.object(services.requests, "get") as get:
        assert services.download_image("/media/content/x.png", 1) == "/media/content/x.png"
        get.assert_not_called()
