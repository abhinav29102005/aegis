FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv==0.6.12

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY modules ./modules
COPY services/api ./services/api
COPY services/worker ./services/worker

RUN uv sync --frozen --no-dev --python 3.12

CMD ["uv", "run", "--no-sync", "python", "-m", "aegis_worker.main"]
