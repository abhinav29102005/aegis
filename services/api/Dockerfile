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

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uv", "run", "--no-sync", "uvicorn", "aegis_api.app:get_default_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
