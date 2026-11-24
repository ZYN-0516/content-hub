# 生产镜像：gunicorn 跑 Django，whitenoise 提供静态文件
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

# 系统依赖：MySQL 客户端库（PyMySQL 纯 Python 无需 gcc，Pillow 用 wheel）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmariadb3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

# 静态文件收集在镜像构建期完成；密钥不进入镜像，collectstatic 用占位值
ARG BUILD_SECRET_KEY=build-time-placeholder
ENV SECRET_KEY=${BUILD_SECRET_KEY}
RUN python manage.py collectstatic --noinput

# 非 root 运行
RUN useradd --system --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-"]
