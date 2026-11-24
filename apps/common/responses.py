"""统一响应结构：{"code": 0, "message": "ok", "data": ...}。

约定：code == 0 表示成功，非 0 表示失败（通常取 HTTP 状态码）。
"""
from typing import Any

from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def ok(data: Any = None, message: str = "ok", code: int = 0) -> Response:
    """成功响应。"""
    return Response({"code": code, "message": message, "data": data})


def fail(
    message: str = "error",
    code: int = 1,
    data: Any = None,
    status: int = http_status.HTTP_400_BAD_REQUEST,
) -> Response:
    """失败响应。"""
    return Response({"code": code, "message": message, "data": data}, status=status)


def _extract_message(detail: Any) -> str:
    """从 DRF 的异常 detail 中提取一条可读的 message。"""
    if isinstance(detail, dict):
        if "detail" in detail:
            return _extract_message(detail["detail"])
        for value in detail.values():
            return _extract_message(value)
        return "请求失败"
    if isinstance(detail, (list, tuple)):
        return _extract_message(detail[0]) if detail else "请求失败"
    return str(detail)


def custom_exception_handler(exc, context) -> Response:
    """把 DRF 异常包装成统一响应结构。"""
    response = drf_exception_handler(exc, context)

    if response is None:
        # 未捕获的异常交给 Django 处理（DEBUG 下会显示堆栈）
        return Response(
            {"code": 500, "message": "服务器内部错误", "data": None},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    original_detail = response.data
    response.data = {
        "code": response.status_code,
        "message": _extract_message(original_detail),
        "data": original_detail,
    }
    return response
