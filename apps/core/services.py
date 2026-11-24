"""AI 生成服务封装。

文本：OpenAI 兼容接口 POST {DASHSCOPE_BASE_URL}/chat/completions
文生图：DashScope 异步接口，提交后轮询任务状态，成功取 results[0].url

API Key 只从 settings（即 .env）读取，代码中不写死。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings

from apps.common.storage import save_generated_file

logger = logging.getLogger(__name__)

DEFAULT_TEXT_MODEL = "qwen-plus"
TEXT_TIMEOUT = 60
IMAGE_REQUEST_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 120

POLL_TIMEOUT = 60
POLL_INTERVAL = 2

_IMAGE_SUBMIT_PATH = "/api/v1/services/aigc/text2image/image-synthesis"
_IMAGE_TASK_PATH = "/api/v1/tasks/{task_id}"

_SUCCESS = "SUCCEEDED"
_FAILED_STATUSES = {"FAILED", "CANCELED", "UNKNOWN"}


class AIServiceError(RuntimeError):
    """AI 服务调用失败。"""


def _api_key() -> str:
    key = getattr(settings, "DASHSCOPE_API_KEY", "")
    if not key:
        raise AIServiceError("DASHSCOPE_API_KEY 未配置，请在 .env 中填写")
    return key


def _text_base_url() -> str:
    base = getattr(settings, "DASHSCOPE_BASE_URL", "").rstrip("/")
    if not base:
        raise AIServiceError("DASHSCOPE_BASE_URL 未配置，请在 .env 中填写")
    return base


def _image_api_base() -> str:
    return getattr(
        settings, "DASHSCOPE_IMAGE_API_BASE", "https://dashscope.aliyuncs.com"
    ).rstrip("/")


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _ensure_ok(response: requests.Response, action: str) -> None:
    if response.status_code >= 400:
        raise AIServiceError(
            f"{action}失败（HTTP {response.status_code}）：{response.text[:500]}"
        )


def text_chat(prompt: str, model: str = DEFAULT_TEXT_MODEL) -> str:
    """调用 OpenAI 兼容文本接口，返回回复文本。"""
    if settings.USE_MOCK_AI:
        logger.info("text_chat 使用 Mock 模式 prompt=%r", prompt[:50])
        return "MOCK: 这是一段测试回复"
    started = time.monotonic()
    logger.info("text_chat 开始 model=%s prompt=%r", model, prompt[:50])
    try:
        response = requests.post(
            f"{_text_base_url()}/chat/completions",
            headers=_headers(_api_key()),
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=TEXT_TIMEOUT,
        )
        _ensure_ok(response, "文本生成")

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIServiceError(f"文本生成返回结构异常：{response.text[:500]}") from exc
    except AIServiceError:
        logger.exception("text_chat 失败 model=%s", model)
        raise
    except requests.RequestException as exc:
        logger.exception("text_chat 网络异常 model=%s", model)
        raise AIServiceError(f"文本生成网络异常：{exc}") from exc

    elapsed = time.monotonic() - started
    logger.info("text_chat 成功 model=%s 耗时=%.2fs", model, elapsed)
    return content


def _mock_image(prompt: str, task_id: int | str | None = None) -> str:
    """本地生成 512x512 的 MOCK 图片，保存到 media/content/ 并返回 URL。"""
    from PIL import Image, ImageDraw, ImageFont

    name = task_id if task_id is not None else int(time.time())
    filename = f"mock_{name}.png"

    target_dir = Path(settings.MEDIA_ROOT) / "content"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename

    image = Image.new("RGB", (512, 512), (0, 102, 204))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=96)
    text = "MOCK"
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (512 - (bbox[2] - bbox[0])) / 2 - bbox[0]
    y = (512 - (bbox[3] - bbox[1])) / 2 - bbox[1]
    draw.text((x, y), text, fill="white", font=font)
    image.save(target, format="PNG")

    media_url = settings.MEDIA_URL
    if not media_url.endswith("/"):
        media_url += "/"
    url = f"{media_url}content/{filename}"
    logger.info("generate_image 使用 Mock 模式 task_id=%s file=%s", name, target)
    return url


def generate_image(
    prompt: str,
    size: str = "1024*1024",
    task_id: int | str | None = None,
) -> str:
    """提交文生图异步任务并轮询，成功返回图片 URL。"""
    size = size.replace("x", "*")
    if settings.USE_MOCK_AI:
        return _mock_image(prompt, task_id)
    started = time.monotonic()
    api_key = _api_key()
    payload = {
        "model": getattr(settings, "DASHSCOPE_IMAGE_MODEL", "wanx2.1-t2i-turbo"),
        "input": {"prompt": prompt},
        "parameters": {"size": size, "n": 1},
    }
    headers = {**_headers(api_key), "X-DashScope-Async": "enable"}
    logger.info("generate_image 提交 prompt=%r size=%s", prompt[:50], size)

    try:
        response = requests.post(
            f"{_image_api_base()}{_IMAGE_SUBMIT_PATH}",
            headers=headers,
            json=payload,
            timeout=IMAGE_REQUEST_TIMEOUT,
        )
        _ensure_ok(response, "提交文生图任务")

        try:
            output = response.json().get("output") or {}
        except ValueError as exc:
            raise AIServiceError(f"提交文生图任务返回非 JSON：{response.text[:500]}") from exc

        task_id = output.get("task_id")
        if not task_id:
            raise AIServiceError(f"提交文生图任务未返回 task_id：{output}")

        logger.info("generate_image 任务已提交 task_id=%s", task_id)
        if output.get("task_status") == _SUCCESS:
            image_url = _extract_image_url(output, task_id)
        else:
            image_url = _poll_image_task(task_id, api_key)
    except AIServiceError:
        logger.exception("generate_image 失败 prompt=%r", prompt[:50])
        raise
    except requests.RequestException as exc:
        logger.exception("generate_image 网络异常 prompt=%r", prompt[:50])
        raise AIServiceError(f"文生图网络异常：{exc}") from exc

    elapsed = time.monotonic() - started
    logger.info(
        "generate_image 成功 task_id=%s 耗时=%.2fs url=%s",
        task_id,
        elapsed,
        image_url,
    )
    return image_url


def _poll_image_task(task_id: str, api_key: str) -> str:
    """轮询文生图任务，最多 POLL_TIMEOUT 秒，每 POLL_INTERVAL 秒一次。"""
    deadline = time.monotonic() + POLL_TIMEOUT
    headers = {"Authorization": f"Bearer {api_key}"}

    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        response = requests.get(
            f"{_image_api_base()}{_IMAGE_TASK_PATH.format(task_id=task_id)}",
            headers=headers,
            timeout=IMAGE_REQUEST_TIMEOUT,
        )
        _ensure_ok(response, "查询文生图任务")

        try:
            output = response.json().get("output") or {}
        except ValueError as exc:
            raise AIServiceError(
                f"查询文生图任务返回非 JSON：{response.text[:500]}"
            ) from exc

        status = output.get("task_status")
        logger.info("generate_image 轮询 task_id=%s status=%s", task_id, status)

        if status == _SUCCESS:
            return _extract_image_url(output, task_id)

        if status in _FAILED_STATUSES:
            reason = output.get("message") or output.get("code") or status
            raise AIServiceError(f"文生图任务失败 task_id={task_id}：{reason}")

    raise AIServiceError(f"文生图任务超时（>{POLL_TIMEOUT}s）task_id={task_id}")


def _extract_image_url(output: dict, task_id: str) -> str:
    results = output.get("results") or []
    if results and results[0].get("url"):
        return results[0]["url"]
    reason = output.get("message") or "结果中不含图片 URL"
    raise AIServiceError(f"文生图任务无可用结果 task_id={task_id}：{reason}")


def download_image(url: str, task_id) -> str:
    """下载图片到 media/content/，返回本地可访问 URL。"""
    if not url.startswith(("http://", "https://")):
        logger.info(
            "download_image 检测到本地 URL，跳过下载 task_id=%s url=%s",
            task_id,
            url,
        )
        return url

    started = time.monotonic()
    logger.info("download_image 开始 task_id=%s url=%s", task_id, url)

    try:
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        if response.status_code >= 400:
            raise AIServiceError(
                f"下载图片失败（HTTP {response.status_code}）：{url}"
            )
        content = response.content
    except AIServiceError:
        logger.exception("download_image 失败 task_id=%s", task_id)
        raise
    except requests.RequestException as exc:
        logger.exception("download_image 网络异常 task_id=%s", task_id)
        raise AIServiceError(f"下载图片网络异常：{exc}") from exc

    suffix = Path(urlparse(url).path).suffix or ".png"
    filename = f"task_{task_id}_{int(time.time())}{suffix}"
    local_url = save_generated_file(content, filename, subdir="content")

    elapsed = time.monotonic() - started
    logger.info(
        "download_image 成功 task_id=%s 耗时=%.2fs local_url=%s",
        task_id,
        elapsed,
        local_url,
    )
    return local_url
