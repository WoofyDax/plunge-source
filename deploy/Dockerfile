# The Plunge hub + lobby services. Build from the plunge/ folder:  docker build -f deploy/Dockerfile -t plunge-server .
# Not tested here (no Docker on the dev PC): build and smoke-test it on your server before relying on it.
FROM python:3.13-slim

RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin plunge \
    && mkdir /data && chown plunge /data
WORKDIR /app
COPY app.py ./
COPY core ./core

USER plunge
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLUNGE_TRUST_PROXY=1 PLUNGE_HUB_DATA=/data LOCALAPPDATA=/tmp
EXPOSE 8788 8787
# default: the hub. The compose file overrides this for the lobby.
CMD ["python", "app.py", "hub", "--bind", "0.0.0.0", "--port", "8788", "--data", "/data"]
