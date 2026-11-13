# The monolith needs all three service packages, so it has its own Dockerfile;
# the layers mirror services/Dockerfile. Build context is services/:
#   docker build -f services/monolith/Dockerfile services/
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY common/ /tmp/common/
RUN pip install /tmp/common && rm -rf /tmp/common
COPY auth/requirements.txt /tmp/req/auth.txt
COPY catalog/requirements.txt /tmp/req/catalog.txt
COPY booking/requirements.txt /tmp/req/booking.txt
RUN pip install -r /tmp/req/auth.txt -r /tmp/req/catalog.txt -r /tmp/req/booking.txt

COPY auth/auth_svc/ /app/auth_svc/
COPY catalog/catalog_svc/ /app/catalog_svc/
COPY booking/booking_svc/ /app/booking_svc/
COPY monolith/monolith_svc/ /app/monolith_svc/

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
RUN mkdir -p /data/storage/tickets /data/storage/reports && chown -R app:app /data/storage
USER app

EXPOSE 8000
CMD ["uvicorn", "--factory", "monolith_svc.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
