"""Flask application: read-only local git browser. No outbound HTTP."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path, PurePosixPath

from flask import Flask, Response, abort, redirect, render_template, request, url_for

from gitweb_local import git_ops, md_render, syntax

MAX_BLOB = 2 * 1024 * 1024  # bytes; larger files show notice instead of full body
MAX_DIFF = 900_000  # characters; larger diffs are truncated before highlighting


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
            meta = git_ops.show_commit_meta(repo, full_sha)
            patch = git_ops.show_commit_patch(repo, full_sha)
        except git_ops.GitError:
            abort(404)
        refs = git_ops.list_refs(repo)
        parent_sha = git_ops.parent_commit(repo, full_sha)
        has_patch = bool(patch.strip())
        diff_truncated = False
        diff_body = patch
        if has_patch and len(diff_body) > MAX_DIFF:
            diff_body = diff_body[:MAX_DIFF] + "\n\n... (diff truncated) ...\n"
            diff_truncated = True
        diff_html = ""
        if has_patch:
            try:
                diff_html = syntax.highlight_diff(diff_body)
            except Exception:
                diff_html = ""
        diff_css = syntax.diff_stylesheet()
        return render_template(
            "commit.html",
            ref=full_sha,
            sha=full_sha,
            meta=meta,
            patch=patch,
            has_patch=has_patch,
            diff_html=diff_html,
            diff_css=diff_css,
            truncated=diff_truncated,
            parent_sha=parent_sha,
            refs=refs,
            active_tab="commits",
            ref_switch="commit",
            switch_path="",
        )

    @app.get("/compare")
    def compare():
        base_in = request.args.get("base", "").strip()
        head_in = request.args.get("head", "").strip()
        refs = git_ops.list_refs(repo)
        base_resolved = head_resolved = ""
        diff_html = ""
        error = ""
        truncated = False
        no_changes = False
        ref_nav = git_ops.head_ref(repo)
        if head_in:
            try:
                head_resolved = git_ops.rev_parse(repo, head_in)
                ref_nav = head_resolved
            except git_ops.GitError:
                error = f"Could not resolve “compare” revision: {head_in!r}"
        if base_in and not error:
            try:
                base_resolved = git_ops.rev_parse(repo, base_in)
                if not head_in:
                    ref_nav = base_resolved
            except git_ops.GitError:
                error = f"Could not resolve base revision: {base_in!r}"
        if base_in and head_in and not error:
            if base_resolved == head_resolved:
                error = "Base and compare revisions are the same."
            else:
                try:
                    raw = git_ops.diff_commits(repo, base_resolved, head_resolved)
                    if not raw.strip():
                        no_changes = True
                    else:
                        body = raw
                        if len(body) > MAX_DIFF:
                            body = body[:MAX_DIFF] + "\n\n... (diff truncated) ...\n"
                            truncated = True
                        diff_html = syntax.highlight_diff(body)
                except git_ops.GitError as e:
                    error = str(e) or "Could not produce a diff."
        return render_template(
            "compare.html",
            base=base_in,
            head=head_in,
            base_resolved=base_resolved,
            head_resolved=head_resolved,
            diff_html=diff_html,
            diff_css=syntax.diff_stylesheet(),
            error=error,
            truncated=truncated,
            no_changes=no_changes,
            refs=refs,
            ref=ref_nav,
            active_tab="compare",
            ref_switch="tree",
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
        render_highlight = False
        html_code: str | None = None
        syntax_css = ""
        if (
            not render_markdown
            and not truncated
            and kind == "text"
            and text is not None
        ):
            try:
                html_code = syntax.highlight_code(text, rel_path)
                if html_code:
                    render_highlight = True
                    syntax_css = syntax.code_stylesheet()
            except Exception:
                render_highlight = False
                html_code = None
                syntax_css = ""
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
            render_highlight=render_highlight,
            html_code=html_code,
            syntax_css=syntax_css,
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
