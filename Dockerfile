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
    && find /app -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && python -c "import sys; sys.path.insert(0, '/app/mcp_server'); import core; \
ps = core.discover_problems(['/app/problems']); print('baked problems:', sorted(ps)); \
assert ps, 'no problems in image'"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Extra directories searched for problems, ahead of the baked-in ones. Lets a
# Taiga `preloaded_files` mount add or override a problem without a rebuild —
# mount the problem folder at /mnt/problems/<problem_id>/.
ENV INVERSE_TASKS_PROBLEM_DIRS=/mnt/problems:/app/problems

# Taiga ignores the image ENTRYPOINT/CMD and runs the problem's
# `startup_command` instead (wiki: features/container_runtimes.md). Set that to:
#
#   python -u /app/mcp_server/server.py --problem-id <your-problem-id>
#
# Passing --problem-id puts the server in "bound mode", where each action the
# oracle declares becomes a first-class MCP tool (evaluate, help, ...) instead
# of the generic query(action, params). Omit it and the server still works, it
# just publishes the generic surface. CMD below only makes `docker run` usable
# for local smoke-testing.
CMD ["python", "-u", "/app/mcp_server/server.py"]
