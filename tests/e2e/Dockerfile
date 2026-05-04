# Bonfire E2E Release-Gate Box
# LOCAL EXECUTION ONLY. Never in CI.
# Validates: a clean-box Claude CLI can install Bonfire and ship a fixture ticket.
#
# Build:  docker build -t bonfire-e2e:local -f tests/e2e/Dockerfile tests/e2e
# Run:    tests/e2e/scripts/e2e-box.sh <wave> [fixture-ref]

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        python3.12 \
        python3.12-venv \
        python3-pip \
        build-essential \
        gnupg \
        jq \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20 via NodeSource — required for Claude CLI
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI — pinned for release-gate reproducibility.
# Bump policy lives in docs/release-gates.md § "claude-cli bump policy".
RUN npm install -g @anthropic-ai/claude-code@2.1.123

WORKDIR /workspace

COPY scripts/e2e-runner.sh /usr/local/bin/e2e-runner
RUN chmod +x /usr/local/bin/e2e-runner

# Bake the in-box prompt template — claude-cli reads this verbatim.
COPY prompts/runner-prompt.md /usr/local/bin/e2e-prompt.txt

# Defense in depth: drop privileges before the runner executes.
# /home/box/.claude is the OAuth credential mount target — operators on Claude
# Max bind-mount their host's ~/.claude/.credentials.json into this directory.
RUN useradd -m -u 1000 box \
    && mkdir -p /workspace/out /workspace/target /home/box/.claude \
    && chown -R box:box /workspace /home/box/.claude

USER box

ENTRYPOINT ["/usr/local/bin/e2e-runner"]
