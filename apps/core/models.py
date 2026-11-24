from django.conf import settings
from django.db import models


class GenerationModel(models.Model):
    """可用的 AI 生成模型。"""

    class Provider(models.TextChoices):
        BAILIAN = "bailian", "百炼"
        DEEPSEEK = "deepseek", "DeepSeek"

    name = models.CharField("模型名称", max_length=100)
    version = models.CharField("版本", max_length=50)
    provider = models.CharField("提供商", max_length=20, choices=Provider.choices)
    model_code = models.CharField("模型标识", max_length=100)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "生成模型"
        verbose_name_plural = "生成模型"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} {self.version}"


class ReferenceImage(models.Model):
    """用户上传的参考图。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="用户",
        on_delete=models.CASCADE,
        related_name="reference_images",
    )
    file = models.ImageField("参考图", upload_to="references/")
    width = models.PositiveIntegerField("宽度", null=True, blank=True)
    height = models.PositiveIntegerField("高度", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "参考图"
        verbose_name_plural = "参考图"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"参考图#{self.pk} - {self.file.name}"


class GenerationTask(models.Model):
    """内容生成任务。"""

    class TaskType(models.TextChoices):
        IMAGE = "image", "图片"
        VIDEO = "video", "视频"

    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        RUNNING = "running", "生成中"
        SUCCESS = "success", "成功"
        FAILED = "failed", "失败"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="用户",
        on_delete=models.CASCADE,
        related_name="generation_tasks",
    )
    task_type = models.CharField("任务类型", max_length=10, choices=TaskType.choices)
    prompt = models.TextField("提示词")
    style = models.CharField("风格", max_length=100, blank=True, default="")
    reference_image = models.ForeignKey(
        ReferenceImage,
        verbose_name="参考图",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_tasks",
    )
    canvas_w = models.PositiveIntegerField("画布宽度", default=0)
    canvas_h = models.PositiveIntegerField("画布高度", default=0)
    ratio = models.CharField("宽高比", max_length=20, blank=True, default="")
    model = models.ForeignKey(
        GenerationModel,
        verbose_name="生成模型",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_tasks",
    )
    parameters = models.JSONField("扩展参数", default=dict, blank=True)
    status = models.CharField(
        "状态",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "生成任务"
        verbose_name_plural = "生成任务"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"任务#{self.pk} {self.get_task_type_display()} {self.prompt[:20]}"


class Content(models.Model):
    """生成后的内容作品。"""

    class ContentType(models.TextChoices):
        IMAGE = "image", "图片"
        VIDEO = "video", "视频"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PENDING = "pending", "待审核"
        PUBLISHED = "published", "已发布"
        REJECTED = "rejected", "已驳回"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="作者",
        on_delete=models.CASCADE,
        related_name="contents",
    )
    title = models.CharField("标题", max_length=255)
    content_type = models.CharField(
        "内容类型",
        max_length=10,
        choices=ContentType.choices,
    )
    file = models.FileField("文件", upload_to="content/")
    file_format = models.CharField("文件格式", max_length=20, blank=True, default="")
    width = models.PositiveIntegerField("宽度", null=True, blank=True)
    height = models.PositiveIntegerField("高度", null=True, blank=True)
    duration = models.PositiveIntegerField(
        "时长（秒）",
        null=True,
        blank=True,
    )
    resolution = models.CharField("分辨率", max_length=50, blank=True, default="")
    status = models.CharField(
        "状态",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    task = models.ForeignKey(
        GenerationTask,
        verbose_name="生成任务",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contents",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)

    class Meta:
        verbose_name = "内容"
        verbose_name_plural = "内容"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class ReviewTask(models.Model):
    """内容审核任务。"""

    class Status(models.TextChoices):
        PENDING = "pending", "待审核"
        APPROVED = "approved", "已通过"
        REJECTED = "rejected", "已驳回"

    content = models.ForeignKey(
        Content,
        verbose_name="内容",
        on_delete=models.CASCADE,
        related_name="review_tasks",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="审核人",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_tasks",
    )
    status = models.CharField(
        "状态",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    comment = models.TextField("审核意见", blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)

    class Meta:
        verbose_name = "审核任务"
        verbose_name_plural = "审核任务"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"审核#{self.pk} - {self.get_status_display()}"


class Comment(models.Model):
    """内容评论。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="用户",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    content = models.ForeignKey(
        Content,
        verbose_name="内容",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    text = models.TextField("评论内容")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "评论"
        verbose_name_plural = "评论"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} 评论了 {self.content}"
