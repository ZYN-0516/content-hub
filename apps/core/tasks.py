"""Celery 异步生成任务。"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from urllib.parse import urlparse

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Content, GenerationTask
from .services import download_image, generate_image

logger = logging.getLogger(__name__)

VIDEO_PLACEHOLDER_MESSAGE = "视频生成开发中"


def _parse_dimensions(size: str) -> tuple[int | None, int | None]:
    parts = size.lower().replace("*", "x").split("x")
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        return int(parts[0]), int(parts[1])
    return None, None


def _media_relative(url: str) -> str:
    """把 /media/content/... 转成 FileField 需要的相对路径 content/..."""
    path = urlparse(url).path if url.startswith(("http://", "https://")) else url
    media_url = settings.MEDIA_URL
    if path.startswith(media_url):
        return path[len(media_url):]
    return path.lstrip("/")


def _build_title(task: GenerationTask) -> str:
    prompt = (task.prompt or "").strip().splitlines()
    first_line = prompt[0] if prompt else ""
    return first_line[:30] or f"任务#{task.id} 生成图片"


def _is_cancelled(task_id: int) -> bool:
    """从数据库读取最新取消标记，避免 worker 内存中的旧状态。"""
    return bool(
        GenerationTask.objects.filter(pk=task_id, parameters__cancelled=True).exists()
    )


def _cancel_result(task_id: int) -> dict:
    """任务已取消：把状态落回 failed，不落库、不覆盖结果。

    worker 进入时已把状态置为 running，早退时必须显式写回 failed，
    否则前端轮询会永远停留在「生成中」。
    """
    logger.info("任务已取消，放弃后续步骤 task_id=%s", task_id)
    GenerationTask.objects.filter(pk=task_id).update(
        status=GenerationTask.Status.FAILED, updated_at=timezone.now()
    )
    return {"task_id": task_id, "status": GenerationTask.Status.FAILED, "cancelled": True}


@shared_task(name="apps.core.tasks.generate_task")
def generate_task(task_id: int):
    """执行生成任务：图片走 AI 生成并落库，视频暂占位失败。"""
    try:
        task = GenerationTask.objects.get(pk=task_id)
    except GenerationTask.DoesNotExist:
        logger.error("generate_task 任务不存在 task_id=%s", task_id)
        return {"task_id": task_id, "status": "missing"}

    if task.status != GenerationTask.Status.PENDING:
        logger.info(
            "generate_task 跳过非 pending 任务 task_id=%s status=%s",
            task_id,
            task.status,
        )
        return {"task_id": task_id, "status": task.status}

    task.status = GenerationTask.Status.RUNNING
    task.save(update_fields=["status", "updated_at"])
    started = time.monotonic()
    logger.info("generate_task 开始 task_id=%s type=%s", task_id, task.task_type)

    try:
        if task.task_type == GenerationTask.TaskType.VIDEO:
            parameters = dict(task.parameters or {})
            parameters["error"] = VIDEO_PLACEHOLDER_MESSAGE
            task.parameters = parameters
            task.status = GenerationTask.Status.FAILED
            task.save(update_fields=["status", "parameters", "updated_at"])
            logger.info(
                "generate_task 视频任务占位失败 task_id=%s 耗时=%.2fs",
                task_id,
                time.monotonic() - started,
            )
            return {
                "task_id": task_id,
                "status": task.status,
                "error": VIDEO_PLACEHOLDER_MESSAGE,
            }

        size = getattr(settings, "DASHSCOPE_IMAGE_SIZE", "1024x1024")

        # 生成前检查：用户在排队阶段取消则直接放弃
        if _is_cancelled(task.id):
            return _cancel_result(task.id)

        remote_url = generate_image(task.prompt, task_id=task.id)

        # 下载前检查：AI 已出图但用户取消，不再落盘、不建内容
        if _is_cancelled(task.id):
            return _cancel_result(task.id)

        local_url = download_image(remote_url, task.id)

        # 落库前再检查一次，避免状态被覆盖回 success
        if _is_cancelled(task.id):
            return _cancel_result(task.id)

        width, height = _parse_dimensions(size)
        file_format = Path(urlparse(local_url).path).suffix.lstrip(".") or "png"

        content = Content.objects.create(
            author=task.user,
            title=_build_title(task),
            content_type=Content.ContentType.IMAGE,
            file=_media_relative(local_url),
            file_format=file_format,
            width=width,
            height=height,
            resolution=size,
            status=Content.Status.DRAFT,
            task=task,
        )

        parameters = dict(task.parameters or {})
        parameters["content_id"] = content.id
        task.parameters = parameters
        task.status = GenerationTask.Status.SUCCESS
        task.save(update_fields=["status", "parameters", "updated_at"])

        logger.info(
            "generate_task 成功 task_id=%s content_id=%s 耗时=%.2fs",
            task_id,
            content.id,
            time.monotonic() - started,
        )
        return {
            "task_id": task_id,
            "content_id": content.id,
            "status": task.status,
        }

    except Exception as exc:  # noqa: BLE001 - 任何失败都要落库
        logger.exception("generate_task 失败 task_id=%s", task_id)
        parameters = dict(task.parameters or {})
        parameters["error"] = str(exc)
        task.parameters = parameters
        task.status = GenerationTask.Status.FAILED
        task.save(update_fields=["status", "parameters", "updated_at"])
        return {"task_id": task_id, "status": task.status, "error": str(exc)}
