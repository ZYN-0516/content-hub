"""OpenAI 兼容接口客户端（阿里云百炼 / DashScope）。

所有密钥、地址均来自 .env（经 settings 读取），代码中不出现任何硬编码密钥。

用法：
    from apps.common.ai_client import text_chat, generate_image

    answer = text_chat("你好")                      # -> str
    image_url = generate_image("一只在写代码的猫")   # -> str（/media/... 或远端 URL）
"""
from __future__ import annotations

import base64
from io import BytesIO
from uuid import uuid4

import requests
from django.conf import settings

DEFAULT_TEXT_MODEL = "qwen-plus"
REQUEST_TIMEOUT = 60
IMAGE_TIMEOUT = 180


class AIClientError(RuntimeError):
    """AI 接口调用失败。"""


def _config():
    """每次调用时读取配置，便于测试时覆盖 settings / 重启后生效。"""
    api_key = getattr(settings, "DASHSCOPE_API_KEY", "")
    base_url = getattr(settings, "DASHSCOPE_BASE_URL", "").rstrip("/")
    if not api_key:
        raise AIClientError("DASHSCOPE_API_KEY 未配置，请在 .env 中填写")
    if not base_url:
        raise AIClientError("DASHSCOPE_BASE_URL 未配置，请在 .env 中填写")
    return api_key, base_url


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _raise_for_error(response: requests.Response, action: str) -> None:
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise AIClientError(f"{action}失败（HTTP {response.status_code}）：{detail}")


def text_chat(prompt: str, model: str = DEFAULT_TEXT_MODEL) -> str:
    """调用 OpenAI 兼容的 /chat/completions，返回纯文本内容。"""
    api_key, base_url = _config()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = requests.post(
        f"{base_url}/chat/completions",
        headers=_headers(api_key),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    _raise_for_error(response, "文本生成")

    try:
        return response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise AIClientError(f"文本生成返回结构异常：{response.text}") from exc


def generate_image(prompt: str) -> str:
    """调用 OpenAI 兼容的 /images/generations，返回图片 URL。

    若服务只返回 b64_json，则落盘到 media/ 并返回本地 URL。
    """
    from apps.common.storage import save_generated_file

    api_key, base_url = _config()
    payload = {
        "model": getattr(settings, "DASHSCOPE_IMAGE_MODEL", "wanx2.1-t2i-turbo"),
        "prompt": prompt,
        "n": 1,
        "size": getattr(settings, "DASHSCOPE_IMAGE_SIZE", "1024*1024"),
    }
    response = requests.post(
        f"{base_url}/images/generations",
        headers=_headers(api_key),
        json=payload,
        timeout=IMAGE_TIMEOUT,
    )
    _raise_for_error(response, "图片生成")

    try:
        item = response.json()["data"][0]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AIClientError(f"图片生成返回结构异常：{response.text}") from exc

    if item.get("url"):
        return item["url"]

    if item.get("b64_json"):
        content = base64.b64decode(item["b64_json"])
        return save_generated_file(BytesIO(content), name=f"ai-{uuid4().hex}.png")

    raise AIClientError(f"图片生成未返回 url 或 b64_json：{response.text}")


def has_deepseek() -> bool:
    """是否配置了 DeepSeek 密钥（预留，后续可切换文本模型）。"""
    return bool(getattr(settings, "DEEPSEEK_API_KEY", ""))
