# Generic runtime for Inverse Task problems, served to Taiga over MCP (stdio).
#
# The image is oracle-agnostic: it ships an engine that reads whatever problems
# live under problems/<problem_id>/ and exposes exactly the probe surface each
# expert's oracle declares. Adding a task means adding a folder — no changes
# here. See docs/AUTHORING.md.
FROM python:3.11-slim

# Taiga's low-level container requirements (wiki: onboarding/01_welcome.md,
# "Low-Level Image Requirements for Running a Container in Taiga"):
# bash/sh, free, grep, lscpu, uptime, cat, find on PATH; `python` resolvable as
# a binary; and /etc/ssl/certs, /usr/local/share/ca-certificates/custom-ca.crt,
# /workdir present even if empty.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        coreutils \
        findutils \
        grep \
        procps \
        util-linux \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/local/bin/python3 /usr/local/bin/python \
    && mkdir -p /etc/ssl/certs /usr/local/share/ca-certificates /workdir \
    && touch /usr/local/share/ca-certificates/custom-ca.crt

# Assert the requirements rather than assuming the package names provide them.
# Debian moves utilities between packages across releases (lscpu in particular),
# and a missing one surfaces as an opaque Taiga preflight failure long after the
# build. Fail here instead, naming the binary.
RUN set -eu; \
    for binary in bash sh free grep lscpu uptime cat find mkdir dirname mv python python3; do \
        command -v "$binary" >/dev/null 2>&1 || { \
            echo "FATAL: required binary '$binary' is not on PATH (see Taiga wiki:" \
                 "onboarding/01_welcome.md, Low-Level Image Requirements)"; exit 1; }; \
    done; \
    for directory in /etc/ssl/certs /workdir; do \
        [ -d "$directory" ] || { echo "FATAL: required directory '$directory' missing"; exit 1; }; \
    done; \
    [ -f /usr/local/share/ca-certificates/custom-ca.crt ] \
        || { echo "FATAL: /usr/local/share/ca-certificates/custom-ca.crt missing"; exit 1; }; \
    echo "low-level image requirements: all present"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server/ /app/mcp_server/
COPY tools/ /app/tools/

# Ship only each problem's runtime subset. collect_problems.py is an allowlist
# (problem.md, config.yaml, oracle/, golden/, grader/*.py), so the intended
# solver, the shortcut/trap solver, the near-miss table, and the calibration
# notes never enter the image even if an expert adds new authoring files.
COPY docker/collect_problems.py /tmp/collect_problems.py
COPY problems/ /tmp/problems_src/
RUN python /tmp/collect_problems.py /tmp/problems_src /app/problems \
    && rm -rf /tmp/problems_src /tmp/collect_problems.py \
    && find /app -name '__pycache__' -type d -prune -exec rm -rf {} +

# Verify the wiring against the *real* mcp package, which exists only here — the
# unit tests stub it. Enumerates the published tools through FastMCP, then runs
# setup_problem -> query -> submit_answer -> grade_problem and asserts the golden
# answer scores 1.0 and a wrong one scores 0.0, in both tool modes. A broken
# FastMCP integration fails the build rather than surfacing as a mystery at job
# time. The problem id is derived, so removing a problem cannot break the gate.
RUN set -eu; \
    export INVERSE_TASKS_PROBLEM_DIRS=/app/problems; \
    export PYTHONDONTWRITEBYTECODE=1; \
    python -c "import mcp, pydantic; print('mcp', mcp.__version__ if hasattr(mcp, '__version__') else '?', '| pydantic', pydantic.VERSION)"; \
    PID="$(python -c "import sys; sys.path.insert(0, '/app/mcp_server'); import core; \
ps = sorted(core.discover_problems()); assert ps, 'no problems baked into the image'; print(ps[0])")"; \
    echo "selftest problem: $PID"; \
    python -u /app/mcp_server/server.py --selftest --problem-id "$PID"; \
    python -u /app/mcp_server/server.py --selftest --named-tools --problem-id "$PID"; \
    python /app/tools/validate_problem.py --no-form-values

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Extra directories searched for problems, ahead of the baked-in ones. Lets a
# Taiga `preloaded_files` mount add or override a problem without a rebuild —
# mount the problem folder at /mnt/problems/<problem_id>/.
ENV INVERSE_TASKS_PROBLEM_DIRS=/mnt/problems:/app/problems

# Taiga ignores the image ENTRYPOINT/CMD and runs the problem's
# `startup_command` instead (wiki: features/container_runtimes.md). Set that to:
#
#   python -u /app/mcp_server/server.py
#
# That publishes query / submit_answer / describe_oracle — the model probes the
# oracle through `query`. Optionally add `--named-tools --problem-id <id>` to
# publish one tool per declared action instead (evaluate, help, ...); it needs
# the id because MCP sends its tool list before Taiga calls setup_problem.
#
# CMD only makes `docker run -i <image>` usable as a local smoke test.
CMD ["python", "-u", "/app/mcp_server/server.py"]
