# TryOut: one container with the API, the web pages and the background jobs.
# Build: docker build -t tryout .   Run: docker run --env-file .env -p 7860:7860 tryout

# Stage 1: install the Python dependencies with uv (uv itself stays in this stage).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2: the app.
FROM python:3.12-slim
# ffmpeg converts browser recordings (webm, mp4) for speech to text. A static build: about 80 MB instead of the
# 420 MB the Debian package pulls in.
COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/ffmpeg
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=7860
WORKDIR /app
COPY backend backend
COPY frontend frontend
COPY migrations migrations
COPY scripts scripts
RUN useradd --create-home app
USER app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python", "-c", "import urllib.request, os; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ['PORT'])"]

# Migrate, then serve. One worker: background jobs run in this process. --proxy-headers so login cookies are marked
# Secure behind the host's HTTPS proxy.
CMD ["sh", "-c", "alembic -c migrations/alembic.ini upgrade head && exec uvicorn backend.app:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips='*'"]
