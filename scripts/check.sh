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
echo "===== G-2 coverage gate (pytest --cov; fails under 85%) ====="
# Measured total: 89% (2026-10-21). Threshold 85% keeps ~4pt headroom above
# the acceptance-criteria floor (agent/tools/storage >= 80%).
"$PY" -m pytest --cov=src --cov-report=term-missing --cov-fail-under=85
if [ $? -eq 0 ]; then report pass "G-2 coverage >= 85%"; else report fail "G-2 coverage >= 85%"; fi

echo
echo "===== G-3 secret scan (git grep rc=1 passes; rc=0/2 blocks) ====="
# Scans git-tracked text files only (no caches or build artifacts; -I skips
# binaries). Scope: maintained code and user-facing docs; the archival records
# under docs/handoff|plans|proposals|research are excluded (they may quote
# placeholder key shapes for historical accuracy).
# The (^|[^a-z0-9_]) prefix class prevents false positives on identifiers such
# as "task-creation" or "task-<hex>" (the letters sk- inside "task-") while
# still matching real keys standing alone after quotes, spaces or punctuation.
git grep -nIiE "(^|[^a-z0-9_])sk-[a-z0-9_-]{8,}|api[_-]?key[[:space:]]*=[[:space:]]*[\"'][^\"']+" \
  -- src tests web examples skills scripts README.md .env.example pyproject.toml .github docs \
  ':!docs/handoff' ':!docs/plans' ':!docs/proposals' ':!docs/research'
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
