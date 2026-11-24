from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """自定义用户：邮箱唯一，登录同时支持 username 或 email。"""

    class Role(models.TextChoices):
        MEMBER = "member", "成员"
        REVIEWER = "reviewer", "审核员"
        ADMIN = "admin", "管理员"

    email = models.EmailField("邮箱", unique=True)
    role = models.CharField(
        "角色",
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    nickname = models.CharField("昵称", max_length=50, blank=True, default="")
    level = models.PositiveIntegerField("等级", default=1)
    points = models.IntegerField("积分", default=0)

    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"
        ordering = ["-date_joined"]

    def __str__(self) -> str:
        return self.username
