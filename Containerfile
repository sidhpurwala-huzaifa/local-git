# Local read-only git browser. Build: podman build -t local-gitweb -f Containerfile .
#
# LISTEN ADDRESS: Default HOST is 0.0.0.0 so `podman run -p ...` (bridge) can reach the
# process. Published ports still map only on the host if you use -p 127.0.0.1:8080:8080.
# For loopback-only *inside* the container, use --network host and -e HOST=127.0.0.1.
#
# Example (typical Podman / Docker bridge):
#   podman run --rm \
#     -p 127.0.0.1:8080:8080 \
#     -v /path/to/CHECKOUT:/repo:ro,Z \
#     -e REPO_PATH=/repo \
#     local-gitweb
#
# The app does not call external HTTP APIs. Prefer a read-only volume mount.

FROM docker.io/library/python:3.12-alpine

RUN apk add --no-cache git \
  && git config --global --add safe.directory '*'

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gitweb_local ./gitweb_local

ENV REPO_PATH=/repo
ENV HOST=0.0.0.0
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "exec python -m gitweb_local --repo \"$REPO_PATH\" --host \"$HOST\" --port \"$PORT\""]
