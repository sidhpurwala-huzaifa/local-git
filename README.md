# local-git (gitweb_local)

A small **read-only** web UI for a **local git checkout** (for example a clone created with `gh repo clone`). It runs on your machine, uses only `git` subprocess calls against that tree, and does not call external HTTP APIs.

You get a browser experience similar to browsing code on a git host: file tree, **syntax-highlighted** source files (via **Pygments**), commit history, **colored unified diffs** on each commit, a **Compare** view for any two revisions, **rendered Markdown** for `.md` / `.markdown` files, and a “View raw” link where relevant.

## Requirements

- Python 3.12+ (for local runs)
- `git` on `PATH`
- Optional: [Podman](https://podman.io/) (or Docker) to run the supplied container image

## Run locally

```bash
cd /path/to/this/repo
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m gitweb_local --repo /path/to/your/checkout --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/`.

Environment variables (optional): `REPO_PATH`, `HOST`, `PORT` — same meaning as the CLI flags where applicable.

## Run with Podman

Build:

```bash
podman build -t local-gitweb -f Containerfile .
```

**Linux (recommended):** bind the app to loopback and use host networking so the browser on the same machine can reach it without exposing the app on `0.0.0.0` inside the container.

```bash
podman run --rm --network host \
  -v /path/to/your/checkout:/repo:ro,Z \
  -e REPO_PATH=/repo \
  -e PORT=8080 \
  localhost/local-gitweb:latest
```

**Bridge / `-p` (e.g. Podman Machine on macOS):** forwarded traffic may not reach a listener bound only to `127.0.0.1` inside the container. If the page does not load, bind inside the container and restrict on the host:

```bash
podman run --rm \
  -p 127.0.0.1:8080:8080 \
  -v /path/to/your/checkout:/repo:ro,Z \
  -e REPO_PATH=/repo \
  -e HOST=0.0.0.0 \
  localhost/local-gitweb:latest
```

Mount the checkout **read-only** (`:ro`) when you can.

## Features

| Area | Behavior |
|------|------------|
| Tree | Lists directories and files; subdirectory listing uses `git ls-tree` in a way that matches real git semantics. |
| Blobs | Recognized source types (e.g. `.py`, `.c`, `.rs`, `.go`, …) are **syntax-highlighted** with line numbers; other text uses a plain block. Binary files are not rendered as text. |
| Markdown | Files ending in `.md` or `.markdown` are rendered as HTML (fenced code, tables, etc.), sanitized with **nh3**. Large files over the blob preview limit stay as plain text preview. |
| Raw | `/raw/<ref>/<path>` serves plain text (or octet-stream for non-text). Linked from Markdown and highlighted source blobs. |
| Commits | Log; each commit shows metadata plus a **colored diff** (Pygments `DiffLexer`, GitHub-dark–style theme). |
| Compare | **Compare** tab: unified `git diff` between two revisions you enter (branches, tags, or SHAs). |
| Refs | Branches and tags (resolved to commits) in the header switcher. |

## Security and privacy

- The application does not implement remotes, fetch, or outbound HTTP to third parties.
- Default listen address for the Python entrypoint is **`127.0.0.1`**. Use host-only port mapping (`127.0.0.1:8080:8080`) on the host when you use bridge networking with `HOST=0.0.0.0`.
- Markdown is treated as **untrusted**: HTML is sanitized after conversion.

## Project layout

- `gitweb_local/` — Flask app, templates, static CSS, git helpers, Markdown rendering.
- `requirements.txt` — Python dependencies.
- `Containerfile` — OCI image (Alpine + Python + `git`).

## License

No license file is included in this repository; add one if you distribute or reuse the code.
