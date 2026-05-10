"""Flask application: read-only local git browser. No outbound HTTP."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path, PurePosixPath

from flask import Flask, Response, abort, redirect, render_template, request, url_for

from gitweb_local import git_ops, md_render

MAX_BLOB = 2 * 1024 * 1024  # bytes; larger files show notice instead of full body


def create_app(repo_path: str | None = None) -> Flask:
    repo = repo_path or os.environ.get("REPO_PATH", "").strip()
    if not repo:
        raise RuntimeError("REPO_PATH is not set and no repo_path was passed")
    repo = str(Path(repo).resolve())
    if not Path(repo).is_dir():
        raise RuntimeError(f"REPO_PATH is not a directory: {repo}")
    try:
        git_ops.head_ref(repo)
    except git_ops.GitError as e:
        raise RuntimeError(f"Not a usable git repository at {repo}: {e}") from e

    app = Flask(
        "gitweb_local",
        template_folder=str(Path(__file__).resolve().parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    app.config["REPO_PATH"] = repo

    @app.context_processor
    def inject_repo() -> dict:
        return {
            "repo_name": Path(repo).name,
            "default_ref": _default_ref(repo),
        }

    @app.get("/")
    def index():
        ref = request.args.get("ref") or _default_ref(repo)
        try:
            sha = git_ops.rev_parse(repo, ref)
        except git_ops.GitError:
            abort(404)
        return redirect(url_for("tree", ref=sha, path=""))

    @app.get("/commits")
    def commits():
        ref = request.args.get("ref") or _default_ref(repo)
        try:
            sha = git_ops.rev_parse(repo, ref)
        except git_ops.GitError:
            abort(404)
        rows = git_ops.log(repo, sha, limit=100)
        refs = git_ops.list_refs(repo)
        return render_template(
            "commits.html",
            ref=sha,
            rows=rows,
            refs=refs,
            active_tab="commits",
            ref_switch="commits",
            switch_path="",
        )

    @app.get("/commit/<sha>")
    def commit(sha: str):
        try:
            full_sha = git_ops.rev_parse(repo, sha)
        except git_ops.GitError:
            abort(404)
        try:
            full = git_ops.show_commit_full(repo, full_sha)
        except git_ops.GitError:
            abort(404)
        refs = git_ops.list_refs(repo)
        return render_template(
            "commit.html",
            ref=full_sha,
            sha=full_sha,
            full=full,
            refs=refs,
            active_tab="commits",
            ref_switch="commit",
            switch_path="",
        )

    @app.get("/tree/<ref>/")
    @app.get("/tree/<ref>/<path:path>")
    def tree(ref: str, path: str = ""):
        try:
            sha = git_ops.rev_parse(repo, ref)
            rel = git_ops.sanitize_relpath(path)
            entries = git_ops.ls_tree(repo, sha, rel)
        except git_ops.GitError:
            abort(404)
        refs = git_ops.list_refs(repo)
        parent = ""
        if rel:
            parent = str(PurePosixPath(rel).parent)
            if parent == ".":
                parent = ""
        crumbs: list[tuple[str, str]] = []
        if rel:
            acc: list[str] = []
            for seg in rel.split("/"):
                acc.append(seg)
                crumbs.append((seg, "/".join(acc)))
        return render_template(
            "tree.html",
            ref=sha,
            path=rel,
            entries=entries,
            refs=refs,
            parent_path=parent,
            breadcrumbs=crumbs,
            active_tab="code",
            ref_switch="tree",
            switch_path=rel,
        )

    @app.get("/raw/<ref>/<path:path>")
    def raw_blob(ref: str, path: str):
        """Plain text (or octet-stream) view for 'View raw' on rendered Markdown."""
        try:
            sha = git_ops.rev_parse(repo, ref)
            kind, data = git_ops.cat_file_blob(repo, sha, path)
        except git_ops.GitError:
            abort(404)
        rel_path = git_ops.sanitize_relpath(path)
        if kind != "text":
            return Response(data, mimetype="application/octet-stream")
        try:
            body = data.decode("utf-8")
        except UnicodeDecodeError:
            body = data.decode("latin-1")
        return Response(
            body,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{Path(rel_path).name}"'},
        )

    @app.get("/blob/<ref>/<path:path>")
    def blob(ref: str, path: str):
        try:
            sha = git_ops.rev_parse(repo, ref)
            kind, data = git_ops.cat_file_blob(repo, sha, path)
        except git_ops.GitError:
            abort(404)
        refs = git_ops.list_refs(repo)
        truncated = len(data) > MAX_BLOB
        if truncated:
            preview = data[:MAX_BLOB]
            kind = git_ops.guess_text_kind(preview)
            display = preview
        else:
            display = data
        text = None
        if kind == "text":
            try:
                text = display.decode("utf-8")
            except UnicodeDecodeError:
                text = display.decode("latin-1")
        rel_path = git_ops.sanitize_relpath(path)
        render_markdown = (
            not truncated
            and kind == "text"
            and text is not None
            and md_render.is_markdown_path(rel_path)
        )
        html_body: str | None = None
        if render_markdown:
            try:
                html_body = md_render.render_markdown(text)
            except Exception:
                render_markdown = False
                html_body = None
        blob_crumbs: list[tuple[str, str | None]] = []
        if rel_path:
            parts = rel_path.split("/")
            for i, seg in enumerate(parts):
                if i == len(parts) - 1:
                    blob_crumbs.append((seg, None))
                else:
                    blob_crumbs.append((seg, "/".join(parts[: i + 1])))
        parent = ""
        if rel_path:
            parent = str(PurePosixPath(rel_path).parent)
            if parent == ".":
                parent = ""
        return render_template(
            "blob.html",
            ref=sha,
            path=rel_path,
            kind=kind,
            text=text,
            truncated=truncated,
            size=len(data),
            render_markdown=render_markdown,
            html_body=html_body,
            refs=refs,
            active_tab="code",
            ref_switch="blob",
            switch_path=rel_path,
            blob_crumbs=blob_crumbs,
            parent_folder=parent,
        )

    return app


def _default_ref(repo: str) -> str:
    sym = git_ops.symbolic_ref(repo)
    if sym:
        return sym
    return git_ops.head_ref(repo)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Local read-only git repository browser.")
    p.add_argument(
        "--repo",
        default=os.environ.get("REPO_PATH", ""),
        help="Path to git working tree (default: REPO_PATH env)",
    )
    p.add_argument(
        "--host",
        default=os.environ.get("HOST", "127.0.0.1"),
        help="Listen address (default 127.0.0.1). Use 0.0.0.0 only if port-publish "
        "from the host does not reach a loopback-bound listener in your setup.",
    )
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    p.add_argument("--debug", action="store_true")
    args = p.parse_args(argv)
    if not args.repo:
        print("error: set --repo or REPO_PATH to your local checkout", file=sys.stderr)
        return 2
    app = create_app(args.repo)
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0
