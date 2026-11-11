FROM ghcr.io/astral-sh/uv:0.11.33 AS uv
FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
WORKDIR /app
COPY --from=build --chown=10001:10001 /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTMCP_CHECK_FOR_UPDATES=off \
    ARR_MCP_TRANSPORT=http \
    ARR_MCP_HOST=0.0.0.0 \
    ARR_MCP_PORT=8000
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import httpx; httpx.get('http://127.0.0.1:8000/healthz', timeout=3).raise_for_status()"]
ENTRYPOINT ["python", "-m", "arr_assistant_mcp.main"]
