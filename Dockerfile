FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install distillr
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY distill/ ./distill/
ENV UV_PYTHON_DOWNLOADS=never
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:${PATH}"

# Install Playwright browsers
RUN playwright install chromium

# Default: run the MCP server
EXPOSE 8765
CMD ["distill-mcp"]
