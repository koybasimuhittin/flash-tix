# The official image renders /etc/nginx/templates/*.template into /etc/nginx/conf.d/ with
# envsubst at startup. The filter limits substitution to our own variables, so nginx's
# runtime variables ($request_id, $host, ...) are left alone.
FROM nginx:stable-alpine

ENV NGINX_ENVSUBST_FILTER="^(BOOKING_RATE_|GATEWAY_)" \
    BOOKING_RATE_LIMIT=5r/s \
    BOOKING_RATE_BURST=10 \
    GATEWAY_ACCESS_LOG=/dev/stdout \
    GATEWAY_RESOLVER=127.0.0.11

COPY templates/ /etc/nginx/templates/
