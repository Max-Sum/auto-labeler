# syntax=docker/dockerfile:1

FROM ghcr.io/flant/shell-operator:v1.19.2

RUN apk --no-cache add python3

COPY --chmod=755 auto-labeler.py /hooks/auto-labeler.py
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

LABEL org.opencontainers.image.source="https://github.com/Max-Sum/auto-labeler"

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["start"]
