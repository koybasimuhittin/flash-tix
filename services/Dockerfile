# One template for every Python service. Build context is services/:
#   docker build -f services/Dockerfile --build-arg SERVICE=auth services/
# For amd64 hosts (e.g. when building on Apple Silicon): docker buildx build --platform linux/amd64 ...
FROM python:3.12-slim

ARG SERVICE
RUN test -n "$SERVICE" || (echo "--build-arg SERVICE=<auth|catalog|booking|monolith> is required" && exit 1)

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SERVICE_MODULE=${SERVICE}_svc.main:create_app

WORKDIR /app

# Dependencies first so code changes don't invalidate the pip layers.
COPY common/ /tmp/common/
RUN pip install /tmp/common && rm -rf /tmp/common
COPY ${SERVICE}/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY ${SERVICE}/ /app/

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
# Local file storage (STORAGE_BACKEND=local). A new, empty Docker volume mounted here copies
# this directory's ownership, so the non-root user can write to it.
RUN mkdir -p /data/storage/tickets /data/storage/reports && chown -R app:app /data/storage
USER app

EXPOSE 8000
# One uvicorn worker per container; scale with replicas. Request logging is done by
# flashtix_common's middleware, so uvicorn's access log is off.
CMD ["sh", "-c", "exec uvicorn --factory \"$SERVICE_MODULE\" --host 0.0.0.0 --port 8000 --no-access-log"]
