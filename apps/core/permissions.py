"""业务权限：审核员判定同时兼容 is_staff 与自定义 role 字段。"""
from rest_framework.permissions import BasePermission

REVIEWER_ROLES = ("reviewer", "admin")
ADMIN_ROLES = ("admin",)


def is_reviewer(user) -> bool:
    """管理员（is_staff）或角色为审核员/管理员的用户可审核。"""
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_staff) or getattr(user, "role", "") in REVIEWER_ROLES


def is_admin(user) -> bool:
    """管理员：is_staff 或角色为 admin。"""
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_staff) or getattr(user, "role", "") in ADMIN_ROLES


class IsReviewer(BasePermission):
    def has_permission(self, request, view):
        return is_reviewer(request.user)


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return is_admin(request.user)


def is_super_user(user) -> bool:
    """超级用户：仅 is_superuser=True，用于角色授予等高敏感操作。"""
    return bool(user and user.is_authenticated and user.is_superuser)


class IsSuperUser(BasePermission):
    def has_permission(self, request, view):
        return is_super_user(request.user)
