# local-git (gitweb_local)

A small **read-only** web UI for a **local git checkout** (for example a clone created with `gh repo clone`). It runs on your machine, uses only **`git` subprocesses** against that tree, and does **not** call external HTTP APIs.

The layout and dark theme are **GitHub-inspired**: repo header with branch/tag picker, underline navigation (**Code**, **Commits**, **Compare**), file tables, commit timeline, and boxed content areas.

## What it does

### Code browser

- **File tree** at any revision (commit SHA, branch, or tag). Subdirectories are listed correctly using `git ls-tree` with the `<rev>:<path>` form so you see real folder contents, not a single self row.
- **Syntax highlighting** for many source types (Python, C/C++, Rust, Go, JavaScript, shell, JSON, YAML, and more) via **[Pygments](https://pygments.org/)**, with **line numbers** and a theme close to **GitHub Dark**.
- **Plain text** files that are not given a dedicated lexer still open in a monospace block.
- **Binary files** are not rendered as text.

### Markdown

- Files named **`.md`** or **`.markdown`** (any case) are rendered as **HTML** (tables, fenced code blocks, lists, etc.) using **Python-Markdown**.
- Output is **sanitized with [nh3](https://github.com/mozilla/nh3)** because repository content is treated as untrusted.
- Very large files are **preview-limited**; the preview falls back to plain text for truncated blobs.

### Raw files

- **`/raw/<ref>/<path>`** returns **`text/plain`** (or **`application/octet-stream`** for binary) so you can open or save the exact bytes.
- Linked as **Raw** from rendered Markdown and from syntax-highlighted source views.

### Commits and diffs

- **Commits** lists recent history (up to 100 commits) for the selected revision.
- Each **commit** page shows the **commit message / headers** and a **colored unified diff** for that commit (Pygments **diff** lexer plus add/remove line highlighting). Very large patches are truncated before highlighting.
- **Compare with parent** appears when the commit has a parent, and opens the **Compare** view pre-filled with `base` = parent and `head` = current commit.

### Compare revisions

- The **Compare** tab (and nav link) lets you diff any two resolved revisions (`git diff old new`) with the same **colored diff** presentation.
- If there are no file changes between the two tips, a short message is shown instead of an empty diff.

### Navigation and refs

- **Branch / tag** dropdown resolves annotated tags to commits and uses SHAs in URLs so paths with slashes in ref names do not break routing.
- **Code / Commits / Compare** tabs keep context for the current revision where applicable.

### Container image

- **Alpine**-based image with Python 3.12 and **`git`**.
- **`HOST=0.0.0.0`** by default so **`podman run -p …`** works; pair with **`-p 127.0.0.1:8080:8080`** on the host to keep traffic local.
- **`git config --global safe.directory '*'`** so volume-mounted repos from your host UID are not blocked as “dubious ownership”.

## Requirements

- Python 3.12+ (for local runs)
- `git` on `PATH`
- Optional: [Podman](https://podman.io/) (or Docker) to run the supplied container image

Python dependencies include **Flask**, **Pygments**, **Markdown**, **nh3**, and **Werkzeug** (see `requirements.txt`).

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

The image defaults to **`HOST=0.0.0.0`** so the server accepts traffic from **published ports** (`-p …`). Restrict access on the **host** with `127.0.0.1` in the publish mapping (recommended):

```bash
podman run --rm \
  -p 127.0.0.1:8080:8080 \
  -v /path/to/your/checkout:/repo:ro,Z \
  -e REPO_PATH=/repo \
  localhost/local-gitweb:latest
```

**Linux, loopback-only inside the container:** use host networking and bind the app to localhost:

```bash
podman run --rm --network host \
  -v /path/to/your/checkout:/repo:ro,Z \
  -e REPO_PATH=/repo \
  -e HOST=127.0.0.1 \
  -e PORT=8080 \
  localhost/local-gitweb:latest
```

The image sets **`git config --global safe.directory '*'`** so Git will read volume-mounted checkouts owned by your host user (avoids “dubious ownership” failures in the container).

Mount the checkout **read-only** (`:ro`) when you can.

## Feature summary (quick reference)

| Area | Behavior |
|------|------------|
| UI | GitHub-style dark layout: header, underline tabs, boxes, breadcrumbs, file icons. |
| Tree | Correct subdirectory listing; branches/tags in header. |
| Source blobs | Pygments highlighting + line numbers when a lexer is known; otherwise plain `<pre>`. |
| Markdown | `.md` / `.markdown` → rendered HTML + nh3 sanitization. |
| Raw | `/raw/...` for exact file bytes. |
| Commits | History list; per-commit metadata + colored patch. |
| Compare | Two-revision `git diff` with colored output; “compare with parent” on commits. |
| Limits | Large blobs and huge diffs are truncated for safety and performance. |

## Security and privacy

- The application does not implement remotes, fetch, or outbound HTTP to third parties.
- The **Python CLI** defaults to **`127.0.0.1`**. The **container image** defaults to **`0.0.0.0`** so port publishing works; keep the service local with **`-p 127.0.0.1:8080:8080`** on the host.
- Markdown is treated as **untrusted**: HTML is sanitized after conversion. Pygments HTML for code and diffs is generated locally (not passed through nh3).

## Project layout

- `gitweb_local/app.py` — Flask routes and wiring.
- `gitweb_local/git_ops.py` — read-only `git` helpers.
- `gitweb_local/md_render.py` — Markdown → sanitized HTML.
- `gitweb_local/syntax.py` — Pygments for code blobs and diffs.
- `gitweb_local/templates/`, `gitweb_local/static/` — UI.
- `requirements.txt` — Python dependencies.
- `Containerfile` — OCI image (Alpine + Python + `git`).

## License

No license file is included in this repository; add one if you distribute or reuse the code.
