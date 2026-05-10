# Local read-only git browser. Build: podman build -t local-gitweb -f Containerfile .
# Default listen: 127.0.0.1 inside the container (no 0.0.0.0).
#
# Linux — recommended (browser on same host uses host loopback):
#   podman run --rm --network host \
#     -v /path/to/CHECKOUT:/repo:ro,Z \
#     -e REPO_PATH=/repo -e PORT=8080 \
#     local-gitweb
#
# Bridge / -p publish (e.g. Podman Machine on macOS): forwarded traffic often does not
# hit the container's loopback. If the page does not load, bind inside the container:
#   -e HOST=0.0.0.0
# and still restrict on the *host* only:
#   -p 127.0.0.1:8080:8080
#
# The app does not call external HTTP APIs. Prefer a read-only volume mount.

FROM docker.io/library/python:3.12-alpine

RUN apk add --no-cache git

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gitweb_local ./gitweb_local

ENV REPO_PATH=/repo
ENV HOST=127.0.0.1
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "exec python -m gitweb_local --repo \"$REPO_PATH\" --host \"$HOST\" --port \"$PORT\""]
