# Generic runtime for Inverse Task problems, served to Taiga over MCP (stdio).
#
# The image is oracle-agnostic: it ships an engine that reads whatever problems
# live under problems/<problem_id>/ and exposes exactly the probe surface each
# expert's oracle declares. Adding a task means adding a folder — no changes
# here. See docs/AUTHORING.md.
ARG INVERSE_TASKS_PLATFORM=linux/amd64
FROM --platform=${INVERSE_TASKS_PLATFORM} python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba

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
        passwd \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/local/bin/python3 /usr/local/bin/python \
    && groupadd --gid 1000 model \
    && useradd --create-home --uid 1000 --gid 1000 --shell /bin/bash model \
    && mkdir -p /etc/ssl/certs /usr/local/share/ca-certificates /workdir \
        /var/lib/inverse-tasks \
    && touch /usr/local/share/ca-certificates/custom-ca.crt \
    && chown model:model /workdir \
    && chmod 0700 /var/lib/inverse-tasks

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
    [ "$(id -u model)" = 1000 ] && [ "$(id -g model)" = 1000 ] \
        || { echo "FATAL: model must be uid/gid 1000"; exit 1; }; \
    echo "low-level image requirements: all present"

WORKDIR /app

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

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

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    INVERSE_TASKS_RUNTIME=build

# Verify the wiring against the *real* mcp package, which exists only here — the
# unit tests stub it. Enumerates the published tools through FastMCP, then runs
# setup_problem -> query_oracle -> submit_answer -> grade_problem and asserts the
# golden answer scores 1.0 and a wrong one scores 0.0, in both tool modes. A
# broken FastMCP integration fails the build rather than surfacing as a mystery
# at job time. Permission hardening is runtime-only, so this check cannot alter
# the problem sources in the image layer.
RUN set -eu; \
    export INVERSE_TASKS_PROBLEM_DIRS=/app/problems; \
    export PYTHONDONTWRITEBYTECODE=1; \
    python -c "import mcp, pydantic; print('mcp', mcp.__version__ if hasattr(mcp, '__version__') else '?', '| pydantic', pydantic.VERSION)"; \
    PID="$(python -c "import sys; sys.path.insert(0, '/app/mcp_server'); import core; \
ps = sorted(core.discover_problems()); assert ps, 'no problems baked into the image'; print(ps[0])")"; \
    echo "selftest problem: $PID"; \
    python -u /app/mcp_server/server.py --selftest --problem-id "$PID"; \
    python -u /app/mcp_server/server.py --selftest --named-tools --problem-id "$PID"; \
    python /app/tools/smoke_mcp.py "$PID"; \
    python /app/tools/validate_problem.py --no-form-values

# Keep all MCP implementation and baked problem data root-only. Taiga starts
# this process as root and executes model-side tools as model:model (1000:1000).
# Unlike deleting secrets after setup, permissions remain correct if Taiga
# restarts the MCP process before grading.
RUN chmod -R go-rwx /app \
    && chmod 0700 /var/lib/inverse-tasks \
    && chmod 0755 /workdir \
    && chown model:model /workdir

ENV INVERSE_TASKS_RUNTIME=taiga \
    INVERSE_TASKS_HARDEN_PERMISSIONS=1 \
    INVERSE_TASKS_REQUIRE_PRIVATE_PROBLEMS=1 \
    INVERSE_TASKS_STATE_PATH=/var/lib/inverse-tasks/session.json \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORKDIR=/workdir

# Extra directories searched for problems, ahead of the baked-in ones. Lets a
# Taiga `preloaded_files` mount add or override a problem without a rebuild —
# mount the problem folder at /mnt/problems/<problem_id>/.
ENV INVERSE_TASKS_PROBLEM_DIRS=/mnt/problems:/app/problems

# Taiga ignores the image ENTRYPOINT/CMD and runs the problem's
# `startup_command` instead (wiki: features/container_runtimes.md). Set that to:
#
#   python -u /app/mcp_server/server.py
#
# That publishes query_oracle / submit_answer / describe_oracle — the model
# probes the oracle through `query_oracle(mode, parameters)`. Optionally add
# `--named-tools --problem-id <id>` to publish one tool per declared action
# instead (evaluate, help, ...); it needs the id because MCP sends its tool
# list before Taiga calls setup_problem.
#
# setup_problem makes mounted problem trees owner-only before returning the
# prompt. Preloaded problem mounts therefore need to be writable by root.
#
# CMD only makes `docker run -i <image>` usable as a local smoke test.
WORKDIR /workdir
CMD ["python", "-u", "/app/mcp_server/server.py"]
