FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Pinned uv release; the same version that produced uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, resolved only from uv.lock. --locked fails the build if pyproject.toml and
# uv.lock disagree, instead of silently re-resolving to newer versions.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev

COPY apps/api/src ./apps/api/src
COPY apps/cli/src ./apps/cli/src
COPY examples/commerce_demo/src ./examples/commerce_demo/src
COPY packages/rift_agent_adapters/src ./packages/rift_agent_adapters/src
COPY packages/rift_core/src ./packages/rift_core/src
COPY packages/rift_experiment_runner/src ./packages/rift_experiment_runner/src
COPY packages/rift_fault_engine/src ./packages/rift_fault_engine/src
COPY packages/rift_invariant_engine/src ./packages/rift_invariant_engine/src

# Install the project itself as a regular (non-editable) package into the locked environment.
RUN uv sync --locked --no-dev --no-editable

# Run as an unprivileged user. /app and /opt/venv stay root-owned and read-only to it.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin rift
USER rift

ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "rift_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
