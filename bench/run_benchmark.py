"""文生图评测集：一键跑出成功率 / 平均耗时 / P95。

用法（在 content-hub 根目录）：
    # 默认 Mock 模式：零费用，验证流程与统计逻辑
    venv\\Scripts\\python.exe bench\\run_benchmark.py

    # 真实调用百炼：会产生费用（20 张图），运行前确认账户余额
    venv\\Scripts\\python.exe bench\\run_benchmark.py --live

    # 只跑前 N 条
    venv\\Scripts\\python.exe bench\\run_benchmark.py --limit 5

输出：
    bench/results/latest.json      最新一次结果（README 引用）
    bench/results/history/*.json   历史结果，便于对比优化前后

说明：
    - 自动指标：成功率、平均耗时、P95、失败原因分布。
    - 语义准确率需人工对照 prompts.json 的 expect 字段核对，写入人工列。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import os  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

import django  # noqa: E402

django.setup()

from django.test import override_settings  # noqa: E402

from apps.core.services import AIServiceError, generate_image  # noqa: E402

PROMPTS_FILE = Path(__file__).resolve().parent / "prompts.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
HISTORY_DIR = RESULTS_DIR / "history"


def load_cases():
    with PROMPTS_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def run_case(case, live: bool, size: str) -> dict:
    started = time.monotonic()
    expected_failure = bool(case.get("expected_failure"))
    result = {
        "id": case["id"],
        "category": case["category"],
        "prompt": case["prompt"],
        "expect": case["expect"],
        "expected_failure": expected_failure,
        "success": False,
        "behaviour_ok": False,  # 预期失败用例：按预期失败即为通过
        "elapsed_s": 0.0,
        "detail": "",
        "semantic_ok": None,  # 人工核对列
    }
    try:
        if not case["prompt"].strip():
            raise AIServiceError("空 prompt（预期失败用例）")
        url = generate_image(case["prompt"], size=size, task_id=f"bench-{case['id']}")
        if not url:
            raise AIServiceError("未返回图片地址")
        result["success"] = True
        result["detail"] = url
    except Exception as exc:  # noqa: BLE001 - 评测需要记录所有失败
        result["detail"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed_s"] = round(time.monotonic() - started, 2)
    result["behaviour_ok"] = result["success"] if not expected_failure else not result["success"]
    return result


def summarize(results: list[dict], live: bool) -> dict:
    normal = [r for r in results if not r["expected_failure"]]
    elapsed = [r["elapsed_s"] for r in normal if r["success"]]
    succeeded = sum(1 for r in normal if r["success"])
    behaviour_ok = sum(1 for r in results if r["behaviour_ok"])
    total = len(results)
    p95 = 0.0
    if elapsed:
        ordered = sorted(elapsed)
        p95 = round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "live" if live else "mock",
        "total": total,
        "normal_cases": len(normal),
        "success": succeeded,
        "success_rate": round(succeeded / len(normal), 4) if normal else 0.0,
        "expected_failure_cases": total - len(normal),
        "behaviour_ok": behaviour_ok,
        "behaviour_ok_rate": round(behaviour_ok / total, 4) if total else 0.0,
        "avg_elapsed_s": round(statistics.mean(elapsed), 2) if elapsed else 0.0,
        "p95_elapsed_s": p95,
        "min_elapsed_s": round(min(elapsed), 2) if elapsed else 0.0,
        "max_elapsed_s": round(max(elapsed), 2) if elapsed else 0.0,
        "semantic_accuracy": "待人工核对 prompts.json 的 expect 字段",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="文生图评测集")
    parser.add_argument("--live", action="store_true", help="真实调用百炼（产生费用）")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 表示全部")
    parser.add_argument("--size", default="1024*1024", help="图片尺寸，默认 1024*1024")
    args = parser.parse_args()

    if args.live:
        from django.conf import settings

        if not getattr(settings, "DASHSCOPE_API_KEY", ""):
            print("[ERROR] --live 需要 .env 中配置 DASHSCOPE_API_KEY")
            return 2
        print("[WARN] --live 模式将真实调用百炼，生成图片会产生费用。")

    cases = load_cases()
    if args.limit > 0:
        cases = cases[: args.limit]

    print(f"运行评测：{len(cases)} 条，模式={'live' if args.live else 'mock'}，尺寸={args.size}")
    # Mock 模式的图片写到 bench 临时目录，不污染项目 media/
    mock_media = RESULTS_DIR / "_mock_assets"
    override_map = {"USE_MOCK_AI": not args.live}
    if not args.live:
        mock_media.mkdir(parents=True, exist_ok=True)
        override_map["MEDIA_ROOT"] = str(mock_media)
    with override_settings(**override_map):
        results = [run_case(case, args.live, args.size) for case in cases]

    summary = summarize(results, args.live)
    payload = {"summary": summary, "results": results}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    latest = RESULTS_DIR / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (HISTORY_DIR / f"{summary['mode']}_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n===== 评测结果 =====")
    for item in results:
        flag = "PASS" if item["behaviour_ok"] else "FAIL"
        tag = " (预期失败)" if item["expected_failure"] else ""
        print(f"[{flag}] #{item['id']:>2} {item['elapsed_s']:>6.2f}s  {item['category']:<14} {item['detail'][:60]}{tag}")
    print("\n===== 汇总 =====")
    for key, value in summary.items():
        if key != "generated_at":
            print(f"{key}: {value}")
    print(f"\n结果已写入：{latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
