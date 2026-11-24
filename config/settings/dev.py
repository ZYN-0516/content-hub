"""开发环境配置：python manage.py check / runserver 默认使用本文件。"""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost", "testserver"])

# 开发时保留 browsable API，方便调试；生产环境仅 JSON
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
}

# 开发环境邮件直接打印到控制台
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
