"""Generator-free independent verification (contract §6.4 path ②, frozen).

verify_bundle is a pure read: read the path → recompute bundle_sha256 (two-key strip rule) and
trials_fingerprint → compare with the recorded values. Calling the generator is forbidden ("integrity
is verifiable without a generator" is the semantics of this path). Not bound by the data/ sandbox write rules.

CLI：python -m src.experiment.verify <bundle_path>
ok → exit 0; failure → exit 1 + stderr details.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from src.experiment.canonical import canonical_json, sha256_hex


class VerifyReport(BaseModel):
    """Verification report: ok=True only when both checks pass."""

    ok: bool
    bundle_sha256_match: bool
    trials_fingerprint_match: bool
    detail: str


def verify_bundle(path: str | Path) -> VerifyReport:
    """Verify bundle integrity (calls no generator)."""
    bundle_path = Path(path)
    try:
        data: object = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerifyReport(
            ok=False,
            bundle_sha256_match=False,
            trials_fingerprint_match=False,
            detail=f"failed to read or parse the bundle: {type(exc).__name__}: {exc}",
        )
    if not isinstance(data, dict):
        return VerifyReport(
            ok=False,
            bundle_sha256_match=False,
            trials_fingerprint_match=False,
            detail=f"bundle top level must be a JSON object, got {type(data).__name__}",
        )

    recorded_sha = data.get("bundle_sha256")
    repro = data.get("reproducibility")
    recorded_tf = repro.get("trials_fingerprint") if isinstance(repro, dict) else None

    problems: list[str] = []
    if not isinstance(recorded_sha, str):
        problems.append("bundle_sha256 missing or not a string")
    if not isinstance(recorded_tf, str):
        problems.append("reproducibility.trials_fingerprint missing or not a string")
    if not isinstance(data.get("trials"), list):
        problems.append("trials missing or not an array")
    if problems:
        return VerifyReport(
            ok=False,
            bundle_sha256_match=False,
            trials_fingerprint_match=False,
            detail=f"incomplete bundle structure: {'; '.join(problems)}",
        )

    # Check ①: recompute bundle_sha256 (strip the bundle_sha256 and generated_at keys, §6.3)
    stripped = {k: v for k, v in data.items() if k not in ("bundle_sha256", "generated_at")}
    recomputed_sha = sha256_hex(canonical_json(stripped))
    sha_match = recomputed_sha == recorded_sha

    # Check ②: trials canonical JSON → sha256 == reproducibility.trials_fingerprint
    recomputed_tf = sha256_hex(canonical_json(data["trials"]))
    tf_match = recomputed_tf == recorded_tf

    ok = sha_match and tf_match
    if ok:
        detail = f"OK: both bundle_sha256 and trials_fingerprint checks passed ({bundle_path})"
    else:
        failed = []
        if not sha_match:
            failed.append(
                f"bundle_sha256 mismatch (recorded {recorded_sha}, recomputed {recomputed_sha})"
            )
        if not tf_match:
            failed.append(
                f"trials_fingerprint mismatch (recorded {recorded_tf}, recomputed {recomputed_tf})"
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
        description="Independently verify ExperimentBundle integrity (recomputes bundle_sha256 and trials_fingerprint; calls no generator)",
    )
    parser.add_argument("path", help="path to the ExperimentBundle JSON file")
    args = parser.parse_args(argv)
    report = verify_bundle(args.path)
    print(report.detail)
    if not report.ok:
        print(f"detail: {report.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
