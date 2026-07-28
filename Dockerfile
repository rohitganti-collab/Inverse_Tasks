# Generic runtime for Inverse Task problems, served to Taiga over MCP (stdio).
# One image serves every problem under problems/<problem_id>/ — see mcp_server/server.py.
FROM python:3.11-slim

# Taiga's low-level container requirements (see wiki: onboarding/01_welcome.md
# "Low-Level Image Requirements"): bash/sh/coreutils/procps/util-linux tools in
# PATH, `python` resolvable as a binary, and a few paths present even if empty.
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

# Only the runtime surface for each problem is copied in — never the
# authoring/calibration artifacts (BRIEF.md, STATE.md, reasoning_trap.md,
# solution/) that name the intended solver or the trap. The model has no
# filesystem-access tool in this environment, but the oracle's hidden
# constants and the trap writeup still shouldn't ship in the image.
COPY mcp_server/ /app/mcp_server/

# Copy each problem's runtime files explicitly (problem.md, oracle/, golden/).
COPY problems/ /app/problems_src/
RUN mkdir -p /app/problems && \
    for d in /app/problems_src/*/; do \
        pid=$(basename "$d"); \
        mkdir -p "/app/problems/$pid/oracle" "/app/problems/$pid/golden"; \
        cp "$d/problem.md" "/app/problems/$pid/problem.md"; \
        cp "$d/oracle/setup.py" "/app/problems/$pid/oracle/setup.py"; \
        cp "$d/golden/expected.json" "/app/problems/$pid/golden/expected.json"; \
    done && \
    rm -rf /app/problems_src

ENV PYTHONUNBUFFERED=1

# Taiga ignores image ENTRYPOINT/CMD and runs the problem's `startup_command`
# instead (see wiki: features/container_runtimes.md) — set that field to
# "python -u /app/mcp_server/server.py" in your problems-metadata JSON.
# CMD below is only so `docker run <image>` works for local smoke-testing.
CMD ["python", "-u", "/app/mcp_server/server.py"]
