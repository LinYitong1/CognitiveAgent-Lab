"""免生成器独立验证（契约 §6.4 路径②，冻结）。

verify_bundle 是纯读操作：读指定路径 → 重算 bundle_sha256（剥离两键规则）与
trials_fingerprint → 与包内记录值比对。禁止调用生成器（"无生成器也可校验完整性"
是本路径的语义）。不受 data/ 沙箱写规则约束。

CLI：python -m src.experiment.verify <bundle_path>
ok → exit 0；失败 → exit 1 + stderr 详情。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from src.experiment.canonical import canonical_json, sha256_hex


class VerifyReport(BaseModel):
    """验证报告：两项检查全过才 ok=True。"""

    ok: bool
    bundle_sha256_match: bool
    trials_fingerprint_match: bool
    detail: str


def verify_bundle(path: str | Path) -> VerifyReport:
    """校验 Bundle 完整性（不调用任何生成器）。"""
    bundle_path = Path(path)
    try:
        data: object = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerifyReport(
            ok=False,
            bundle_sha256_match=False,
            trials_fingerprint_match=False,
            detail=f"读取或解析 bundle 失败: {type(exc).__name__}: {exc}",
        )
    if not isinstance(data, dict):
        return VerifyReport(
            ok=False,
            bundle_sha256_match=False,
            trials_fingerprint_match=False,
            detail=f"bundle 顶层必须是 JSON 对象，实际为 {type(data).__name__}",
        )

    recorded_sha = data.get("bundle_sha256")
    repro = data.get("reproducibility")
    recorded_tf = repro.get("trials_fingerprint") if isinstance(repro, dict) else None

    problems: list[str] = []
    if not isinstance(recorded_sha, str):
        problems.append("bundle_sha256 缺失或不是字符串")
    if not isinstance(recorded_tf, str):
        problems.append("reproducibility.trials_fingerprint 缺失或不是字符串")
    if not isinstance(data.get("trials"), list):
        problems.append("trials 缺失或不是数组")
    if problems:
        return VerifyReport(
            ok=False,
            bundle_sha256_match=False,
            trials_fingerprint_match=False,
            detail=f"bundle 结构不完整: {'; '.join(problems)}",
        )

    # 检查①：重算 bundle_sha256（剥离 bundle_sha256 与 generated_at 两键，§6.3）
    stripped = {k: v for k, v in data.items() if k not in ("bundle_sha256", "generated_at")}
    recomputed_sha = sha256_hex(canonical_json(stripped))
    sha_match = recomputed_sha == recorded_sha

    # 检查②：trials canonical JSON → sha256 == reproducibility.trials_fingerprint
    recomputed_tf = sha256_hex(canonical_json(data["trials"]))
    tf_match = recomputed_tf == recorded_tf

    ok = sha_match and tf_match
    if ok:
        detail = f"OK: bundle_sha256 与 trials_fingerprint 两项校验均通过（{bundle_path}）"
    else:
        failed = []
        if not sha_match:
            failed.append(
                f"bundle_sha256 不匹配（记录值 {recorded_sha}，重算值 {recomputed_sha}）"
            )
        if not tf_match:
            failed.append(
                f"trials_fingerprint 不匹配（记录值 {recorded_tf}，重算值 {recomputed_tf}）"
            )
        detail = f"FAIL: {'; '.join(failed)}"
    return VerifyReport(
        ok=ok,
        bundle_sha256_match=sha_match,
        trials_fingerprint_match=tf_match,
        detail=detail,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.experiment.verify",
        description="独立验证 ExperimentBundle 完整性（重算 bundle_sha256 与 trials_fingerprint，不调用生成器）",
    )
    parser.add_argument("path", help="ExperimentBundle JSON 文件路径")
    args = parser.parse_args(argv)
    report = verify_bundle(args.path)
    print(report.detail)
    if not report.ok:
        print(f"detail: {report.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
