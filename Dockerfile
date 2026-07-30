FROM python:3.12

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock .python-version ./

# Sync dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the application
COPY . .

RUN uv sync --frozen --no-dev

ENTRYPOINT ["uv", "run", "python", "-m", "shroud"]
