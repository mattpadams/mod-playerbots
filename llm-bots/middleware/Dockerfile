FROM python:3.12-slim

WORKDIR /app

# Node.js is needed for the Claude Code CLI, which the Claude Agent SDK
# uses for both the agent loop and OAuth credential management.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir $(python -c "import tomllib, pathlib; d = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(' '.join(d['project']['dependencies']))")

# Non-root user; the SDK reads OAuth creds from $HOME/.claude/.credentials.json
RUN useradd -m -s /bin/bash botrunner \
    && mkdir -p /home/botrunner/.claude \
    && chown botrunner:botrunner /home/botrunner/.claude

COPY . .

USER botrunner

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8180"]
