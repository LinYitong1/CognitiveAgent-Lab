"""沙箱路径安全校验（与 src/tools/file_write.py 的五步规则同语义，可复用实现）。

同步义务：本模块与 file_write.py:39-79 的五步规则保持同步——任何规则变更须两处同改
并回提 Architect（契约 §5.3 冻结裁定；file_write.py 本体禁止修改，故同步注释落位于本文件）。

五步规则（契约顺序冻结）：
1. 字符串级拒绝 `..` 与绝对路径；
2. realpath + is_relative_to 组件边界校验（防 data-evil 前缀歧义）；
3. 沙箱根到目标每一级 lstat 拒绝符号链接（TOCTOU 缓解）；
4. 大小上限（调用方职责：file_write 为 content 字节数，export 为 bundle 字节数）；
5. 沙箱内自动建父目录，覆盖写。

本模块承担第 1~3 步（路径校验）与第 5 步（写盘）；第 4 步由调用方
在写盘前按各自的 BLOCKED 语义执行。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


class SandboxBlocked(Exception):
    """安全拒绝（→ BLOCKED: 前缀）。"""


def _ensure_dir(path: Path) -> None:
    """mkdir 容错：目录已存在（含宿主安全代理把跨进程 EEXIST 包成 PermissionError 的场景）时静默通过。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if not path.is_dir():
            raise


def validate_sandbox_path(path_str: str, sandbox_root: Path) -> Path:
    """五步规则第 1~3 步：校验相对沙箱根的输出路径，返回沙箱内目标绝对路径。"""
    rel_parts = Path(path_str).parts

    # 1. 字符串级拒绝 .. 与绝对路径
    if os.path.isabs(path_str) or ".." in rel_parts:
        raise SandboxBlocked("path traversal")

    # 沙箱根本身允许自动创建（配置指定位置），保证后续锚点存在
    _ensure_dir(sandbox_root)
    sandbox_real = Path(os.path.realpath(sandbox_root))
    target = sandbox_root.joinpath(*rel_parts)

    # 2. realpath + 组件边界前缀校验（防 data-evil 字符串前缀歧义）
    deepest = target
    while not deepest.exists():
        deepest = deepest.parent
    deepest_real = Path(os.path.realpath(deepest))
    if not deepest_real.is_relative_to(sandbox_real):
        raise SandboxBlocked("outside sandbox")

    # 3. 符号链接拒绝：沙箱根到目标每一级 lstat 检查
    current = sandbox_root
    for part in rel_parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            break  # 该级及更深层均不存在，不可能含符号链接
        if stat.S_ISLNK(st.st_mode):
            raise SandboxBlocked("symlink in path")

    return target


def write_sandbox_file(target: Path, data: bytes) -> None:
    """五步规则第 5 步：沙箱内自动创建父目录，覆盖写。"""
    _ensure_dir(target.parent)
    target.write_bytes(data)
