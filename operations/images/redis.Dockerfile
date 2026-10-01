FROM redis:7-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499 AS upstream
RUN sha256sum /usr/local/bin/redis-server /usr/local/bin/redis-cli > /tmp/redis-binaries.sha256

FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6
# Preserve the official Redis 7.4.11 binaries while replacing its older Alpine
# crypto runtime. Redis links only musl and OpenSSL's stable libssl/libcrypto 3 ABI.
RUN apk add --no-cache libssl3 libcrypto3 \
    && addgroup -S -g 10001 redis && adduser -S -D -H -u 10001 -G redis redis \
    && mkdir /data && chown redis:redis /data
COPY --from=upstream /usr/local/bin/redis* /usr/local/bin/
COPY --from=upstream /tmp/redis-binaries.sha256 /usr/local/share/redis-binaries.sha256
RUN sha256sum -c /usr/local/share/redis-binaries.sha256 \
    && redis-server --version && redis-cli --version
ENV REDIS_VERSION=7.4.11
USER redis
WORKDIR /data
CMD ["redis-server", "--save", "", "--appendonly", "no"]
