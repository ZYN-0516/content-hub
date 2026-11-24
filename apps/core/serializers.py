from rest_framework import serializers

from .models import (
    Comment,
    Content,
    GenerationModel,
    GenerationTask,
    ReferenceImage,
    ReviewTask,
)


class GenerationModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenerationModel
        fields = "__all__"
        read_only_fields = ("id", "created_at")


class ReferenceImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenceImage
        fields = "__all__"
        read_only_fields = ("id", "user", "created_at")


class GenerationTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenerationTask
        fields = "__all__"
        read_only_fields = ("id", "user", "status", "created_at", "updated_at")

    def validate_reference_image(self, value):
        request = self.context.get("request")
        if value is not None and request is not None:
            if value.user_id != request.user.id:
                raise serializers.ValidationError("不能引用其他用户的参考图")
        return value


class ContentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = Content
        fields = (
            "id", "author", "author_name", "title", "content_type", "file",
            "file_format", "width", "height", "duration", "resolution",
            "status", "task", "created_at", "published_at",
        )
        read_only_fields = (
            "id",
            "author",
            "status",
            "created_at",
            "published_at",
        )


class ContentMineSerializer(ContentSerializer):
    """个人中心：自己的作品 + 最新审核状态/意见。"""

    review_status = serializers.SerializerMethodField()
    review_comment = serializers.SerializerMethodField()

    class Meta(ContentSerializer.Meta):
        fields = ContentSerializer.Meta.fields + ("review_status", "review_comment")

    def _latest_review(self, obj):
        if not hasattr(obj, "_latest_review_cache"):
            obj._latest_review_cache = obj.review_tasks.order_by("-created_at").first()
        return obj._latest_review_cache

    def get_review_status(self, obj):
        review = self._latest_review(obj)
        return review.status if review else ""

    def get_review_comment(self, obj):
        review = self._latest_review(obj)
        return review.comment if review else ""


class ReviewTaskSerializer(serializers.ModelSerializer):
    # 审核列表需要直接展示作品信息，避免前端再逐个请求内容详情
    content_title = serializers.CharField(source="content.title", read_only=True)
    content_file = serializers.CharField(source="content.file.url", read_only=True)
    author_name = serializers.CharField(source="content.author.username", read_only=True)
    reviewer_name = serializers.SerializerMethodField()

    def get_reviewer_name(self, obj):
        return obj.reviewer.username if obj.reviewer_id else ""

    class Meta:
        model = ReviewTask
        fields = (
            "id", "content", "content_title", "content_file", "author_name",
            "reviewer", "reviewer_name", "status", "comment",
            "created_at", "reviewed_at",
        )
        read_only_fields = (
            "id", "content", "content_title", "content_file", "author_name",
            "reviewer", "status", "created_at", "reviewed_at",
        )


class CommentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.username", read_only=True)
    content_title = serializers.CharField(source="content.title", read_only=True)

    class Meta:
        model = Comment
        fields = (
            "id", "user", "user_name", "content", "content_title",
            "text", "created_at",
        )
        read_only_fields = ("id", "user", "user_name", "created_at")
