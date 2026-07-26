#!/usr/bin/env bash
# Every HQ suite. Needs a server on $HQ_BASE for the API contract test.
set -u
cd /Users/meetdeshani/Desktop/HQ
BASE="${HQ_BASE:-http://127.0.0.1:8077}"
fail=0
echo "── offline suites ──"
for t in tests/permissions_seed_test.py tests/zoho_client_test.py tests/zoho_sync_test.py; do
  printf "  %-34s " "$(basename "$t")"
  if venv/bin/python "$t" >/dev/null 2>&1; then echo "OK"; else echo "FAILED"; fail=1; fi
done
echo "── API contract (needs a running server) ──"
printf "  %-34s " "api_smoke.py"
out=$(venv/bin/python tests/api_smoke.py --base "$BASE" 2>&1 | grep -E "^[0-9]+ passed" | tail -1)
echo "${out:-no result — is a server running on $BASE?}"
echo "$out" | grep -q ", 0 failed" || fail=1
exit $fail
