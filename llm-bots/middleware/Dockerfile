FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for sentence-transformers and the Claude Code CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir $(python -c "import tomllib, pathlib; d = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(' '.join(d['project']['dependencies']))")

# Create a non-root user for the Claude Code CLI credentials
RUN useradd -m -s /bin/bash botrunner \
    && mkdir -p /home/botrunner/.claude \
    && chown botrunner:botrunner /home/botrunner/.claude

COPY . .

USER botrunner

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8180"]
