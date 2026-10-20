#!/usr/bin/env bash
# CI 门禁：G-1 ~ G-4 + G-5a + G-5b 六项，逐项独立执行、显式 if 判定退出码。
# 不使用 set -e（G-3 的 grep rc=1 是通过态，set -e 会中断脚本）。
# 聚合退出码：任一分项失败即非 0。
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

# pyright 需要 Node.js 运行时：优先用 pip 包自带的 nodejs-bin，
# 缺失时回退到 managed node（确保 G-5a 不会因 PATH 缺 node 而失败）
export PATH="/Users/linyitong/.workbuddy/binaries/node/versions/22.22.2-6/bin:$PATH"

overall=0

report() {  # report <pass|fail> <分项名>
  if [ "$1" = "pass" ]; then
    echo "[PASS] $2"
  else
    echo "[FAIL] $2"
    overall=1
  fi
}

echo "===== G-1 测试全绿（pytest） ====="
"$PY" -m pytest
if [ $? -eq 0 ]; then report pass "G-1 pytest 全绿"; else report fail "G-1 pytest 全绿"; fi

echo
echo "===== G-2 覆盖率（pytest --cov，M0 仅要求可运行不报错） ====="
"$PY" -m pytest --cov=src --cov-report=term-missing
if [ $? -eq 0 ]; then report pass "G-2 覆盖率命令可运行"; else report fail "G-2 覆盖率命令可运行"; fi

echo
echo "===== G-3 密钥扫描（grep rc=1 通过；rc=0/2 阻断） ====="
grep -rniE "(sk-[a-z0-9_-]{8,}|api[_-]?key[[:space:]]*=[[:space:]]*[\"'][^\"']+)" src/ tests/ web/
g3_rc=$?
if [ "$g3_rc" -eq 1 ]; then
  report pass "G-3 无硬编码密钥"
elif [ "$g3_rc" -eq 0 ]; then
  report fail "G-3 发现疑似硬编码密钥（见上方 grep 输出）"
else
  report fail "G-3 扫描出错（grep rc=${g3_rc}）"
fi

echo
echo "===== G-4 分层依赖检查（scripts.check_layers） ====="
"$PY" -m scripts.check_layers
if [ $? -eq 0 ]; then report pass "G-4 分层依赖正确"; else report fail "G-4 分层依赖正确"; fi

echo
echo "===== G-5a 静态类型检查（pyright src/） ====="
"$PY" -m pyright src/
if [ $? -eq 0 ]; then report pass "G-5a pyright 零错误"; else report fail "G-5a pyright 零错误"; fi

echo
echo "===== G-5b 语法编译检查（compileall -q src/） ====="
"$PY" -m compileall -q src/
if [ $? -eq 0 ]; then report pass "G-5b compileall 通过"; else report fail "G-5b compileall 通过"; fi

echo
if [ "$overall" -eq 0 ]; then
  echo "======== 六项门禁全部 PASS ========"
else
  echo "======== 存在 FAIL 分项，见上方报告 ========"
fi
exit "$overall"
