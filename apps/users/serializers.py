from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()

# 账号：字母开头，4-20 位，仅允许字母 / 数字 / 下划线
USERNAME_REGEX = r"^[A-Za-z][A-Za-z0-9_]{3,19}$"
# 密码：8-20 位，至少包含一个字母和一个数字，允许常见符号
PASSWORD_REGEX = r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_@#$%^&*+=!?.\-]{8,20}$"

username_validator = RegexValidator(
    regex=USERNAME_REGEX,
    message="账号需字母开头，4-20 位，只能包含字母、数字或下划线",
)
password_validator = RegexValidator(
    regex=PASSWORD_REGEX,
    message="密码需 8-20 位，且至少包含一个字母和一个数字",
)


class UserSerializer(serializers.ModelSerializer):
    """用户信息输出 / 个人资料更新。"""

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "nickname",
            "role",
            "level",
            "points",
            "is_staff",
            "is_superuser",
            "first_name",
            "last_name",
            "date_joined",
        )
        read_only_fields = (
            "id", "role", "level", "points",
            "is_staff", "is_superuser", "date_joined",
        )


class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        max_length=20,
        validators=[username_validator],
    )
    password = serializers.CharField(
        write_only=True,
        validators=[password_validator, validate_password],
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ("username", "email", "password")

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("该用户名已被注册")
        return value

    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("该邮箱已被注册")
        return email

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class LoginSerializer(TokenObtainPairSerializer):
    """在 username 字段中同时接受用户名或邮箱。"""

    def validate(self, attrs):
        identifier = attrs.get(self.username_field) or self.initial_data.get("email")

        if identifier and not User.objects.filter(username=identifier).exists():
            user = User.objects.filter(email__iexact=identifier).first()
            if user:
                attrs[self.username_field] = user.get_username()

        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data
