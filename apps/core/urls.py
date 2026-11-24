from django.urls import path

from .views import (
    AdminCommentDeleteView,
    AdminCommentListView,
    AdminContentView,
    AdminUserListView,
    AdminUserRoleView,
    CommentListCreateView,
    ContentDetailView,
    ContentListView,
    ContentMineView,
    ContentPublishView,
    ContentSearchView,
    ContentSubmitReviewView,
    GenerationTaskCancelView,
    GenerationTaskDetailView,
    GenerationTaskListCreateView,
    ReviewApproveView,
    ReviewRejectView,
    ReviewTaskListView,
)

app_name = "core"

urlpatterns = [
    # 生成任务
    path("generation/tasks/", GenerationTaskListCreateView.as_view(), name="generation-task-list"),
    path("generation/tasks/<int:pk>/", GenerationTaskDetailView.as_view(), name="generation-task-detail"),
    path("generation/tasks/<int:pk>/cancel/", GenerationTaskCancelView.as_view(), name="generation-task-cancel"),
    # 内容
    path("content/", ContentListView.as_view(), name="content-list"),
    path("content/mine/", ContentMineView.as_view(), name="content-mine"),
    path("content/search/", ContentSearchView.as_view(), name="content-search"),
    path("content/<int:pk>/", ContentDetailView.as_view(), name="content-detail"),
    path("content/<int:pk>/publish/", ContentPublishView.as_view(), name="content-publish"),
    path("content/<int:pk>/submit-review/", ContentSubmitReviewView.as_view(), name="content-submit-review"),
    # 审核
    path("review/tasks/", ReviewTaskListView.as_view(), name="review-task-list"),
    path("review/tasks/<int:pk>/approve/", ReviewApproveView.as_view(), name="review-task-approve"),
    path("review/tasks/<int:pk>/reject/", ReviewRejectView.as_view(), name="review-task-reject"),
    # 评论
    path("comments/", CommentListCreateView.as_view(), name="comment-list"),
    # 管理后台
    path("admin/content/", AdminContentView.as_view(), name="admin-content-list"),
    path("admin/content/<int:pk>/", AdminContentView.as_view(), name="admin-content-detail"),
    path("admin/users/", AdminUserListView.as_view(), name="admin-user-list"),
    path("admin/users/<int:pk>/role/", AdminUserRoleView.as_view(), name="admin-user-role"),
    path("admin/comments/", AdminCommentListView.as_view(), name="admin-comment-list"),
    path("admin/comments/<int:pk>/", AdminCommentDeleteView.as_view(), name="admin-comment-delete"),
]
