# python:3.12-slim (multi-arch OCI index manifest digest)
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/home/aegis/.cache/uv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv==0.10.12 && \
    groupadd --system aegis && \
    useradd --system --gid aegis --home-dir /home/aegis --create-home aegis && \
    mkdir -p /var/lib/aegis/evidence /home/aegis/.cache/uv

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY modules ./modules
COPY services/api ./services/api
COPY services/worker ./services/worker

RUN uv sync --frozen --no-dev --python 3.12 && \
    rm -rf /tmp/uv-cache && \
    chown -R aegis:aegis /app /var/lib/aegis /home/aegis

USER aegis

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "aegis_api.app:get_default_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
