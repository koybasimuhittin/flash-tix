# The official image renders /etc/nginx/templates/*.template into /etc/nginx/conf.d/ with
# envsubst at startup. The filter limits substitution to our own variables, so nginx's
# runtime variables ($request_id, $host, ...) are left alone.
FROM nginx:stable-alpine

ENV NGINX_ENVSUBST_FILTER="^(BOOKING_RATE_|GATEWAY_)" \
    BOOKING_RATE_LIMIT=5r/s \
    BOOKING_RATE_BURST=10 \
    GATEWAY_ACCESS_LOG=/dev/stdout \
    GATEWAY_RESOLVER=127.0.0.11 \
    GATEWAY_AUTH_UPSTREAM=auth-service:8000 \
    GATEWAY_CATALOG_UPSTREAM=catalog-service:8000 \
    GATEWAY_BOOKING_UPSTREAM=booking-service:8000 \
    GATEWAY_FRONTEND_UPSTREAM=frontend:80

COPY templates/ /etc/nginx/templates/
