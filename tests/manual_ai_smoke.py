"""AI 接口手动冒烟测试（不会被自动执行）。

运行：
    .\\venv\\Scripts\\python.exe tests\\test_ai_smoke.py
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from apps.core.services import AIServiceError, generate_image, text_chat  # noqa: E402


def smoke_text() -> bool:
    print("===== text_chat 冒烟 =====")
    try:
        reply = text_chat("说OK")
    except AIServiceError as exc:
        print(f"[FAIL] text_chat: {exc}")
        return False
    print(f"[OK] text_chat 回复：{reply}")
    return True


def smoke_image() -> bool:
    print("===== generate_image 冒烟 =====")
    try:
        url = generate_image("红色圆形")
    except AIServiceError as exc:
        print(f"[FAIL] generate_image: {exc}")
        return False
    print(f"[OK] generate_image URL：{url}")
    return True


if __name__ == "__main__":
    text_ok = smoke_text()
    image_ok = smoke_image()
    print("===== 结果 =====")
    print(f"text_chat: {'PASS' if text_ok else 'FAIL'}")
    print(f"generate_image: {'PASS' if image_ok else 'FAIL'}")
    sys.exit(0 if text_ok and image_ok else 1)
