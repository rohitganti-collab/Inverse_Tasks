#!/bin/bash
# Reproducible proof that a built image resists the attacks that worked against
# a shipped one. Run it against any candidate image before publishing:
#
#     docker build --platform linux/amd64 -t inverse-tasks:candidate .
#     docker run --rm -i --platform linux/amd64 inverse-tasks:candidate \
#         bash -s < tools/verify_container.sh
#
# Exits non-zero if any check fails. See docs/HARDENING.md for what each one is
# defending against and why it is not hypothetical.
set -u

PROBLEM="${1:-modular-black-box}"
FAILURES=0

pass() { echo "  [ ok ] $1"; }
fail() { echo "  [FAIL] $1"; FAILURES=$((FAILURES + 1)); }
hdr()  { echo; echo "=== $1 ==="; }

# A file the model must not be able to read. `cat` alone is not a test: in a
# pipeline its exit status is masked, which is exactly how an earlier version of
# this script reported a leak that was not there.
refuse_read() {
    local path="$1" label="$2" out
    if out="$(su model -s /bin/bash -c "cat '$path' 2>&1")"; then
        fail "$label is READABLE by the model: ${out:0:80}"
    elif [[ "$out" == *"Permission denied"* || "$out" == *"No such file"* ]]; then
        pass "$label is not readable by the model"
    else
        fail "$label: unexpected result: ${out:0:120}"
    fi
}

hdr "setting up an attempt the way Taiga does"
mkdir -p /mnt/problems
cp -r "/app/problems/$PROBLEM" /mnt/problems/ 2>/dev/null || {
    echo "no such problem: $PROBLEM"; exit 2; }
# Worst case: the mount arrives world-writable.
chmod -R 0777 "/mnt/problems/$PROBLEM"

python - "$PROBLEM" <<'PY'
import json, os, sys
sys.path.insert(0, "/app/mcp_server")
os.environ["INVERSE_TASKS_PROBLEM_DIRS"] = "/mnt/problems:/app/problems"
import server

problem_id = sys.argv[1]
server.setup_problem(problem_id)
server.submit_answer(json.dumps([1, 1]))          # deliberately wrong
grade = server.grade_problem(problem_id, transcript="verify")
payload = json.dumps(
    {"subscores": grade.subscores, "metadata": grade.metadata},
    sort_keys=True, default=str,
)
# Mimic Taiga writing the grade where solver tools can read it.
with open("/workdir/app.log", "w") as handle:
    handle.write(payload)
os.chmod("/workdir/app.log", 0o644)
PY

hdr "the answer must not reach the model"
refuse_read "/mnt/problems/$PROBLEM/golden/expected.json" "golden/expected.json"
refuse_read "/mnt/problems/$PROBLEM/oracle/setup.py"      "oracle/setup.py"
refuse_read "/var/lib/inverse-tasks/session.json"         "attempt state"

GOLDEN_VALUES="$(python -c "
import json,sys
print(' '.join(str(v) for v in json.load(open('/mnt/problems/$PROBLEM/golden/expected.json'))['answer']))
" 2>/dev/null)"

LOG="$(su model -s /bin/bash -c 'cat /workdir/app.log 2>/dev/null')"
leaked=""
for value in $GOLDEN_VALUES; do
    if grep -qE "(^|[^0-9.])$value([^0-9.]|\$)" <<<"$LOG"; then leaked="$leaked $value"; fi
done
if [[ -n "$leaked" ]]; then
    fail "grade log exposes golden value(s):$leaked"
else
    pass "grade log carries no golden values"
fi
grep -q '"expected"' <<<"$LOG" \
    && fail 'grade log contains an "expected" key' \
    || pass 'grade log has no "expected" key'
grep -q 'expected_fingerprint' <<<"$LOG" \
    && pass "grade log reports a fingerprint instead" \
    || fail "grade log has no expected_fingerprint (calibration cannot detect a fixed instance)"

hdr "nothing readable anywhere else on the filesystem"
found="$(su model -s /bin/bash -c "find / -name 'expected.json' -readable 2>/dev/null" | head -5)"
[[ -z "$found" ]] && pass "no readable golden answer on disk" \
                  || fail "readable golden answer(s): $found"
su model -s /bin/bash -c "ls /app >/dev/null 2>&1" \
    && fail "/app is listable by the model" \
    || pass "/app is not listable by the model"
su model -s /bin/bash -c "ls '/mnt/problems/$PROBLEM' >/dev/null 2>&1" \
    && fail "the problem directory is listable by the model" \
    || pass "the problem directory is not listable by the model"

hdr "no submission handoff file to hijack"
handoff="$(su model -s /bin/bash -c "ls /tmp/*submission* /tmp/*inverse-oracle* 2>/dev/null")"
[[ -z "$handoff" ]] && pass "no world-writable submission file under /tmp" \
                    || fail "submission handoff present under /tmp: $handoff"

hdr "the query budget cannot be reset"
python - "$PROBLEM" <<'PY'
import os, sys
sys.path.insert(0, "/app/mcp_server")
os.environ["INVERSE_TASKS_PROBLEM_DIRS"] = "/mnt/problems:/app/problems"
import server

problem_id = sys.argv[1]
server.state.session = None
server.setup_problem(problem_id)
for i in range(3):
    server.query_oracle("evaluate", {"x": i})
used = server.state.session.calls_used
try:
    server.setup_problem(problem_id)
except ValueError:
    print(f"  [ ok ] setup_problem refused re-entry ({used} call(s) already spent)")
    sys.exit(0)
print(f"  [FAIL] setup_problem reset the budget: {used} -> {server.state.session.calls_used}")
sys.exit(1)
PY
[[ $? -ne 0 ]] && FAILURES=$((FAILURES + 1))

hdr "result"
if [[ $FAILURES -eq 0 ]]; then
    echo "ALL CHECKS PASSED"
    exit 0
fi
echo "$FAILURES CHECK(S) FAILED"
exit 1
