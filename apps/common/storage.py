"""文件存储抽象层。

当前使用本地 media/ 目录。将来切换 MinIO / 阿里云 OSS / S3 时，
只需在“存储后端”区域实现新的 Backend 并替换 _backend，不必改动调用方。

对外唯一入口：
    save_generated_file(file, name) -> str  # 返回可访问的 URL
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urljoin
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_name(name: str) -> str:
    """去掉路径并过滤不安全字符，保留扩展名。"""
    base = os.path.basename(name).strip() or "file"
    base = _UNSAFE_CHARS.sub("_", base)
    return base[:120]


class LocalStorageBackend:
    """本地磁盘存储实现（media/ 目录）。"""

    def __init__(self, media_root: Path, media_url: str):
        self.media_root = Path(media_root)
        self.media_url = media_url

    def save(self, file: BinaryIO | bytes, name: str, subdir: str = "generated") -> str:
        subdir = subdir.strip("/") or "generated"
        relative_path = Path(subdir) / timezone.now().strftime("%Y/%m/%d") / name
        absolute_path = self.media_root / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)

        content = file if isinstance(file, (bytes, bytearray)) else file.read()
        with open(absolute_path, "wb") as fh:
            fh.write(content)

        return self.url(str(relative_path.as_posix()))

    def url(self, relative_path: str) -> str:
        return urljoin(self.media_url, relative_path)


# ---------------------------------------------------------------------------
# 存储后端选择：切换云存储时只改这里
# ---------------------------------------------------------------------------
_backend = LocalStorageBackend(settings.MEDIA_ROOT, settings.MEDIA_URL)


def save_generated_file(
    file: BinaryIO | bytes,
    name: str | None = None,
    subdir: str = "generated",
) -> str:
    """保存 AI 生成/上传的文件，返回可访问 URL。

    :param file: 文件对象（含 read()）或 bytes
    :param name: 期望文件名，可省略；会自动加唯一前缀防止覆盖
    :param subdir: 媒体根目录下的子目录，默认 generated；AI 生成内容传 content
    :return: 形如 /media/content/2026/11/24/xxxx.png 的 URL
    """
    safe_name = _sanitize_name(name or "generated.bin")
    unique_name = f"{uuid4().hex}_{safe_name}"
    return _backend.save(file, unique_name, subdir=subdir)
