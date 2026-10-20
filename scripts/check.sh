#!/usr/bin/env bash
# CI gate: G-1 ~ G-4 + G-5a + G-5b, six checks, each run independently with explicit exit-code branching.
# No set -e (grep rc=1 is the pass state for G-3; set -e would abort the script).
# Aggregate exit code: any failed check makes it non-zero.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

# pyright needs a Node.js runtime: prefer the nodejs-bin pip package;
# warn when node is missing from PATH (no machine-specific paths are hardcoded)
if ! command -v node >/dev/null 2>&1; then
  echo "[warn] node not found in PATH; pyright (G-5a) may fail. Install Node.js or the nodejs-bin pip package."
fi

overall=0

report() {  # report <pass|fail> <check name>
  if [ "$1" = "pass" ]; then
    echo "[PASS] $2"
  else
    echo "[FAIL] $2"
    overall=1
  fi
}

echo "===== G-1 all tests green (pytest) ====="
"$PY" -m pytest
if [ $? -eq 0 ]; then report pass "G-1 pytest all green"; else report fail "G-1 pytest all green"; fi

echo
echo "===== G-2 coverage (pytest --cov; M0 only requires the command to run) ====="
"$PY" -m pytest --cov=src --cov-report=term-missing
if [ $? -eq 0 ]; then report pass "G-2 coverage command runs"; else report fail "G-2 coverage command runs"; fi

echo
echo "===== G-3 secret scan (grep rc=1 passes; rc=0/2 blocks) ====="
# -I skips binary files: compiled .pyc artifacts can false-positive when marshal
# reference bytes land adjacent to ASCII strings (e.g. "task-expa002" + ref byte).
# The scan targets source text only.
grep -rniI -E "(sk-[a-z0-9_-]{8,}|api[_-]?key[[:space:]]*=[[:space:]]*[\"'][^\"']+)" src/ tests/ web/
g3_rc=$?
if [ "$g3_rc" -eq 1 ]; then
  report pass "G-3 no hardcoded secrets"
elif [ "$g3_rc" -eq 0 ]; then
  report fail "G-3 suspected hardcoded secret found (see the grep output above)"
else
  report fail "G-3 scan error (grep rc=${g3_rc})"
fi

echo
echo "===== G-4 layering check (scripts.check_layers) ====="
"$PY" -m scripts.check_layers
if [ $? -eq 0 ]; then report pass "G-4 layering correct"; else report fail "G-4 layering correct"; fi

echo
echo "===== G-5a static type check (pyright src/) ====="
"$PY" -m pyright src/
if [ $? -eq 0 ]; then report pass "G-5a pyright zero errors"; else report fail "G-5a pyright zero errors"; fi

echo
echo "===== G-5b syntax compile check (compileall -q src/) ====="
"$PY" -m compileall -q src/
if [ $? -eq 0 ]; then report pass "G-5b compileall passes"; else report fail "G-5b compileall passes"; fi

echo
if [ "$overall" -eq 0 ]; then
  echo "======== all six gates PASS ========"
else
  echo "======== some checks FAILED, see the report above ========"
fi
exit "$overall"
