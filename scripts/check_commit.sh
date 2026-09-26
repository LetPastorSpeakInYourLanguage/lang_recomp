#!/usr/bin/env bash
# Verify the committed tree alone: stash everything uncommitted, run the checks,
# restore. Usage: check_commit.sh [web]
set -u
cd "$(dirname "$0")/.."
stashed=0
if [ -n "$(git status --porcelain)" ]; then
  git stash push -u -q -m "check-commit" && stashed=1
fi
echo "== $(git log --oneline -1)"
fail=0
python -m compileall -q app worker scripts tests >/dev/null || { echo "compile FAILED"; fail=1; }
python -m pytest -q tests 2>&1 | tail -1 | sed 's/^/pytest: /'
python -m pytest -q tests >/dev/null 2>&1 || fail=1
if [ "${1:-}" = "web" ]; then
  (cd web && npx tsc --noEmit >/dev/null 2>&1 && echo "typecheck: ok") || { echo "typecheck FAILED"; fail=1; }
  (cd web && npm run build 2>&1 | grep -q "built in" && echo "build: ok") || { echo "build FAILED"; fail=1; }
fi
if [ $stashed = 1 ]; then git stash pop -q; fi
[ $fail = 0 ] && echo "RESULT: pass" || echo "RESULT: FAIL"
