import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import fail, ok
from config.celery import app as celery_app

from .permissions import IsAdmin, IsReviewer, IsSuperUser

logger = logging.getLogger(__name__)
User = get_user_model()

from .models import Comment, Content, GenerationTask, ReviewTask
from .serializers import (
    CommentSerializer,
    ContentMineSerializer,
    ContentSerializer,
    GenerationTaskSerializer,
    ReviewTaskSerializer,
)
from .tasks import generate_task


def _ctx(request):
    return {"request": request}


def _get_task_for_user(request, pk):
    """任务属于个人数据：包括管理员在内，任何账号只能访问自己创建的任务。"""
    qs = GenerationTask.objects.select_related("model", "reference_image")
    qs = qs.filter(user=request.user)
    return get_object_or_404(qs, pk=pk)


# ---------------------------------------------------------------------------
# 生成任务
# ---------------------------------------------------------------------------
class GenerationTaskListCreateView(APIView):
    """GET /api/generation/tasks/ 列表；POST 创建任务（状态固定为 pending）。"""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        # "我的任务"只返回本人生成的任务；管理员看别人的审核记录走 /api/review/tasks/
        qs = GenerationTask.objects.select_related("model", "reference_image").filter(
            user=request.user
        )
        serializer = GenerationTaskSerializer(qs, many=True, context=_ctx(request))
        return ok(serializer.data)

    def post(self, request):
        serializer = GenerationTaskSerializer(data=request.data, context=_ctx(request))
        serializer.is_valid(raise_exception=True)
        task = serializer.save(
            user=request.user, status=GenerationTask.Status.PENDING
        )

        # 先保存 celery 任务 ID，再异步执行；取消时据此 revoke 后台任务
        parameters = dict(task.parameters or {})
        celery_id = f"gen-task-{task.id}"  # 可预测，便于取消时定位
        parameters["celery_task_id"] = celery_id
        task.parameters = parameters
        task.save(update_fields=["parameters", "updated_at"])

        generate_task.apply_async(args=[task.id], task_id=celery_id)

        return ok(
            {"id": task.id, "status": task.status},
            message="任务创建成功",
        )


class GenerationTaskDetailView(APIView):
    """GET /api/generation/tasks/{id}/ 查看任务状态。"""

    permission_classes = (IsAuthenticated,)

    def get(self, request, pk):
        task = _get_task_for_user(request, pk)
        return ok(GenerationTaskSerializer(task, context=_ctx(request)).data)


class GenerationTaskCancelView(APIView):
    """POST /api/generation/tasks/{id}/cancel/ 取消任务。"""

    permission_classes = (IsAuthenticated,)

    def post(self, request, pk):
        task = _get_task_for_user(request, pk)
        if task.status not in (
            GenerationTask.Status.PENDING,
            GenerationTask.Status.RUNNING,
        ):
            return fail("当前状态不可取消", code=400)

        # 1) 写入取消标记：worker 在每个阶段都会检查，避免继续生成/覆盖状态
        parameters = dict(task.parameters or {})
        parameters["cancelled"] = True
        task.status = GenerationTask.Status.FAILED
        task.parameters = parameters
        task.save(update_fields=["status", "parameters", "updated_at"])

        # 2) 撤销 Celery 任务；即使已开跑，revoke 配合上面的标记也能阻止落库
        celery_id = parameters.get("celery_task_id")
        if celery_id:
            try:
                celery_app.control.revoke(celery_id, terminate=False)
                logger.info("取消任务 task_id=%s 已 revoke celery_id=%s", pk, celery_id)
            except Exception:  # noqa: BLE001 - revoke 失败不影响标记生效
                logger.exception("取消任务 revoke 失败 task_id=%s", pk)

        return ok(
            GenerationTaskSerializer(task, context=_ctx(request)).data,
            message="任务已取消",
        )


# ---------------------------------------------------------------------------
# 内容
# ---------------------------------------------------------------------------
class ContentListView(APIView):
    """GET /api/content/ 只返回已发布内容，允许匿名访问。"""

    permission_classes = (AllowAny,)

    def get(self, request):
        qs = Content.objects.filter(status=Content.Status.PUBLISHED).select_related(
            "author", "task"
        )
        serializer = ContentSerializer(qs, many=True, context=_ctx(request))
        return ok(serializer.data)


class ContentMineView(APIView):
    """GET /api/content/mine/ 当前用户自己的全部作品（含未发布）。"""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        qs = (
            Content.objects.filter(author=request.user)
            .select_related("author", "task")
            .prefetch_related("review_tasks")
        )
        serializer = ContentMineSerializer(qs, many=True, context=_ctx(request))
        return ok(serializer.data)


class ContentDetailView(APIView):
    """GET /api/content/{id}/ 详情；DELETE 删除。"""

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request, pk):
        content = get_object_or_404(
            Content.objects.select_related("author", "task"), pk=pk
        )
        if content.status != Content.Status.PUBLISHED:
            user = request.user
            is_owner = user.is_authenticated and content.author_id == user.id
            if not is_owner and not user.is_staff:
                raise Http404
        return ok(ContentSerializer(content, context=_ctx(request)).data)

    def delete(self, request, pk):
        content = get_object_or_404(Content, pk=pk)
        if not request.user.is_staff and content.author_id != request.user.id:
            raise PermissionDenied("只能删除自己的内容")
        content.delete()
        return ok(None, message="删除成功")


class ContentSearchView(APIView):
    """GET /api/content/search/?q= 按标题模糊搜索已发布内容。"""

    permission_classes = (AllowAny,)

    def get(self, request):
        qs = Content.objects.filter(status=Content.Status.PUBLISHED).select_related(
            "author", "task"
        )
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(title__icontains=q)
        serializer = ContentSerializer(qs, many=True, context=_ctx(request))
        return ok(serializer.data)


class ContentPublishView(APIView):
    """POST /api/content/{id}/publish/ 发布内容。"""

    permission_classes = (IsAuthenticated,)

    def post(self, request, pk):
        content = get_object_or_404(Content, pk=pk)
        if not request.user.is_staff and content.author_id != request.user.id:
            raise PermissionDenied("只能发布自己的内容")

        if content.status != Content.Status.PUBLISHED:
            content.status = Content.Status.PUBLISHED
            if content.published_at is None:
                content.published_at = timezone.now()
            content.save(update_fields=["status", "published_at"])

        return ok(ContentSerializer(content, context=_ctx(request)).data, "发布成功")


class ContentSubmitReviewView(APIView):
    """POST /api/content/{id}/submit-review/ 提交内容进入待审队列。

    状态流转：draft/rejected -> pending，并创建一条待审 ReviewTask。
    驳回后允许修改重新提交，会新建一条审核记录（保留历史）。
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request, pk):
        content = get_object_or_404(Content, pk=pk)
        if not request.user.is_staff and content.author_id != request.user.id:
            raise PermissionDenied("只能提交自己的内容")

        if content.status not in (Content.Status.DRAFT, Content.Status.REJECTED):
            return fail("当前状态不可提交审核", code=400)

        with transaction.atomic():
            content.status = Content.Status.PENDING
            content.save(update_fields=["status"])
            ReviewTask.objects.create(content=content, status=ReviewTask.Status.PENDING)

        return ok(
            ContentSerializer(content, context=_ctx(request)).data,
            message="已提交审核",
        )


# ---------------------------------------------------------------------------
# 审核
# ---------------------------------------------------------------------------
class ReviewTaskListView(APIView):
    """GET /api/review/tasks/ 待审核列表；?status=all 返回全站审核记录（审核员/管理员）。"""

    permission_classes = (IsReviewer,)

    def get(self, request):
        qs = ReviewTask.objects.select_related(
            "content", "reviewer", "content__author"
        )
        if request.query_params.get("status") == "all":
            # 待审核排前面，已处理的按时间倒序，方便管理员先处理待办
            qs = qs.annotate(
                _pending_first=Case(
                    When(status=ReviewTask.Status.PENDING, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            ).order_by("_pending_first", "-created_at")
        else:
            qs = qs.filter(status=ReviewTask.Status.PENDING)
        serializer = ReviewTaskSerializer(qs, many=True, context=_ctx(request))
        return ok(serializer.data)


class ReviewApproveView(APIView):
    """POST /api/review/tasks/{id}/approve/ 审核通过并发布内容。"""

    permission_classes = (IsReviewer,)

    def post(self, request, pk):
        with transaction.atomic():
            review = get_object_or_404(
                ReviewTask.objects.select_for_update(), pk=pk
            )
            if review.status != ReviewTask.Status.PENDING:
                return fail("该审核任务已处理", code=400)

            now = timezone.now()
            review.status = ReviewTask.Status.APPROVED
            review.reviewer = request.user
            review.reviewed_at = now
            review.save(update_fields=["status", "reviewer", "reviewed_at"])

            content = review.content
            content.status = Content.Status.PUBLISHED
            if content.published_at is None:
                content.published_at = now
            content.save(update_fields=["status", "published_at"])

        return ok(
            ReviewTaskSerializer(review, context=_ctx(request)).data,
            message="审核通过",
        )


class ReviewRejectView(APIView):
    """POST /api/review/tasks/{id}/reject/ 驳回内容。"""

    permission_classes = (IsReviewer,)

    def post(self, request, pk):
        comment = request.data.get("comment", "")

        with transaction.atomic():
            review = get_object_or_404(
                ReviewTask.objects.select_for_update(), pk=pk
            )
            if review.status != ReviewTask.Status.PENDING:
                return fail("该审核任务已处理", code=400)

            review.status = ReviewTask.Status.REJECTED
            review.reviewer = request.user
            review.reviewed_at = timezone.now()
            review.comment = comment
            review.save(
                update_fields=["status", "reviewer", "reviewed_at", "comment"]
            )

            content = review.content
            content.status = Content.Status.REJECTED
            content.save(update_fields=["status"])

        return ok(
            ReviewTaskSerializer(review, context=_ctx(request)).data,
            message="已驳回",
        )


# ---------------------------------------------------------------------------
# 评论
# ---------------------------------------------------------------------------
class CommentListCreateView(APIView):
    """GET /api/comments/?content_id= 列表；POST 发表评论（需登录）。"""

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request):
        qs = Comment.objects.select_related("user", "content")
        content_id = request.query_params.get("content_id")
        if content_id:
            if not str(content_id).isdigit():
                return fail("content_id 参数不合法")
            qs = qs.filter(content_id=int(content_id))
        serializer = CommentSerializer(qs, many=True, context=_ctx(request))
        return ok(serializer.data)

    def post(self, request):
        serializer = CommentSerializer(data=request.data, context=_ctx(request))
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return ok(serializer.data, message="评论成功")


# ---------------------------------------------------------------------------
# 管理后台（仅管理员）
# ---------------------------------------------------------------------------
class AdminContentView(APIView):
    """GET 全部作品；PATCH 改标题/状态（DELETE 走 /api/content/{id}/）。"""

    permission_classes = (IsAdmin,)

    def get(self, request):
        qs = (
            Content.objects.select_related("author", "task")
            .prefetch_related("review_tasks")
            .all()
        )
        return ok(ContentMineSerializer(qs, many=True, context=_ctx(request)).data)

    def patch(self, request, pk):
        content = get_object_or_404(Content, pk=pk)
        updates = {}
        if "title" in request.data:
            title = str(request.data.get("title") or "").strip()
            if not title:
                return fail("标题不能为空", code=400)
            updates["title"] = title[:255]
        if "status" in request.data:
            status = request.data.get("status")
            if status not in [value for value, _ in Content.Status.choices]:
                return fail("状态不合法", code=400)
            updates["status"] = status
        if not updates:
            return fail("没有可更新的字段", code=400)
        for key, value in updates.items():
            setattr(content, key, value)
        content.save(update_fields=list(updates))
        return ok(
            ContentMineSerializer(content, context=_ctx(request)).data,
            message="更新成功",
        )


class AdminUserListView(APIView):
    """GET /api/admin/users/ 用户列表（仅超级用户）。"""

    permission_classes = (IsSuperUser,)

    def get(self, request):
        data = [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "is_staff": u.is_staff,
                "is_superuser": u.is_superuser,
                "date_joined": u.date_joined,
            }
            for u in User.objects.all().order_by("id")
        ]
        return ok(data)


class AdminUserRoleView(APIView):
    """PATCH /api/admin/users/{id}/role/ 修改用户角色（仅超级用户）。"""

    permission_classes = (IsSuperUser,)

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        role = request.data.get("role")
        if role not in [value for value, _ in User.Role.choices]:
            return fail("角色不合法", code=400)
        user.role = role
        user.save(update_fields=["role"])
        return ok({"id": user.id, "username": user.username, "role": role}, "角色已更新")


class AdminCommentListView(APIView):
    """GET /api/admin/comments/ 全站评论列表。"""

    permission_classes = (IsAdmin,)

    def get(self, request):
        qs = Comment.objects.select_related("user", "content")
        return ok(CommentSerializer(qs, many=True, context=_ctx(request)).data)


class AdminCommentDeleteView(APIView):
    """DELETE /api/admin/comments/{id}/ 删除评论。"""

    permission_classes = (IsAdmin,)

    def delete(self, request, pk):
        get_object_or_404(Comment, pk=pk).delete()
        return ok(None, message="评论已删除")
