"""测试环境配置：pytest 专用。

- 使用内存 SQLite，不依赖本机 MySQL / Redis，任何人 clone 后都能直接跑测试。
- 强制 USE_MOCK_AI=True：单元测试不调用百炼，零费用。
- Celery 同步执行，便于断言任务副作用。
"""
from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-only-secret-key-not-for-production"
ALLOWED_HOSTS = ["testserver"]

USE_MOCK_AI = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False

# 测试密码哈希用最慢的 PBKDF2 会拖慢几十个用例，这里换成 MD5（仅测试环境）
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# 静音日志，避免测试输出淹没断言结果
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}
