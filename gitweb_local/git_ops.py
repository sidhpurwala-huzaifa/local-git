"""Read-only git operations via subprocess. No remotes, no fetch."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath


class GitError(Exception):
    """Raised when git returns non-zero or output is invalid."""


def _run(repo: str, args: list[str], *, input_bytes: bytes | None = None) -> str:
    cmd = ["git", "-C", repo, *args]
    try:
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git timed out: {' '.join(cmd)}") from e
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise GitError(err or f"git failed ({proc.returncode}): {' '.join(cmd)}")
    return (proc.stdout or b"").decode("utf-8", errors="replace")


def sanitize_relpath(path: str) -> str:
    """Normalize user-supplied path to a safe repo-relative posix path."""
    if not path or path == ".":
        return ""
    p = PurePosixPath(path)
    parts: list[str] = []
    for part in p.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise GitError("invalid path")
        parts.append(part)
    return "/".join(parts)


def rev_parse(repo: str, ref: str) -> str:
    ref = ref.strip()
    if not ref or "\n" in ref or ref.startswith("-"):
        raise GitError("invalid ref")
    out = _run(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    sha = out.strip()
    if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
        raise GitError("invalid commit")
    return sha


def head_ref(repo: str) -> str:
    out = _run(repo, ["rev-parse", "HEAD"]).strip()
    if len(out) != 40:
        raise GitError("cannot resolve HEAD")
    return out


def symbolic_ref(repo: str) -> str | None:
    try:
        return _run(repo, ["symbolic-ref", "-q", "HEAD"]).strip() or None
    except GitError:
        return None


def list_refs(repo: str) -> list[tuple[str, str]]:
    """Return (refname, commit_sha) for branches and tags, sorted."""
    lines = _run(
        repo,
        ["for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags"],
    ).splitlines()
    pairs: list[tuple[str, str]] = []
    for line in lines:
        name = line.strip()
        if not name:
            continue
        try:
            sha = _run(repo, ["rev-parse", "--verify", f"{name}^{{commit}}"]).strip()
        except GitError:
            continue
        if len(sha) == 40:
            pairs.append((name, sha))
    pairs.sort(key=lambda x: x[0].lower())
    return pairs


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    kind: str
    object_id: str
    name: str
    size: int | None  # None for commits/trees


def ls_tree(repo: str, ref: str, path: str) -> list[TreeEntry]:
    """List directory contents at *path* in *ref* (commit SHA).

    Uses ``git ls-tree -z -l --no-abbrev <rev>:<path>`` so that:

    * Subdirectories list their **children** (``rev:dir``), not a single
      self-referential tree row (``rev -- dir``).
    * NUL-terminated records parse reliably (odd filenames, CRLF, ``core.abbrev``).
    """
    rel = sanitize_relpath(path)
    treeish = f"{ref}:{rel}" if rel else ref
    cmd = ["git", "-C", repo, "ls-tree", "-z", "-l", "--no-abbrev", treeish]
    proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise GitError(err or f"git ls-tree failed ({proc.returncode})")
    data = proc.stdout or b""
    entries: list[TreeEntry] = []
    for record in data.split(b"\0"):
        if not record:
            continue
        tab = record.rfind(b"\t")
        if tab < 0:
            continue
        meta_b, name_b = record[:tab], record[tab + 1 :]
        name = name_b.decode("utf-8", errors="surrogateescape")
        meta = meta_b.decode("ascii", errors="surrogateescape").split()
        if len(meta) < 3:
            continue
        mode, kind, oid = meta[0], meta[1], meta[2]
        size_s = meta[3] if len(meta) >= 4 else "-"
        size: int | None
        if size_s == "-":
            size = None
        else:
            try:
                size = int(size_s)
            except ValueError:
                size = None
        entries.append(TreeEntry(mode=mode, kind=kind, object_id=oid, name=name, size=size))
    entries.sort(key=lambda e: (e.kind != "tree", e.name.lower()))
    return entries


def cat_file_blob(repo: str, ref: str, path: str) -> tuple[str, bytes]:
    rel = sanitize_relpath(path)
    if not rel:
        raise GitError("missing blob path")
    spec = f"{ref}:{rel}"
    cmd = ["git", "-C", repo, "cat-file", "blob", spec]
    proc = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise GitError(err or "not a blob")
    data = proc.stdout or b""
    return guess_text_kind(data), data


def guess_text_kind(data: bytes) -> str:
    if not data:
        return "text"
    if b"\x00" in data[:8192]:
        return "binary"
    try:
        data.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        try:
            data.decode("latin-1")
            return "text"
        except UnicodeDecodeError:
            return "binary"


@dataclass(frozen=True)
class CommitRow:
    sha: str
    subject: str
    author: str
    date: str


def log(repo: str, ref: str, limit: int = 50) -> list[CommitRow]:
    fmt = "%H%x1f%s%x1f%an%x1f%ai%x1e"
    out = _run(
        repo,
        ["log", f"-n{max(1, min(limit, 500))}", f"--format={fmt}", ref],
    )
    rows: list[CommitRow] = []
    for record in out.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f")
        if len(parts) != 4:
            continue
        sha, subject, author, date = parts
        if len(sha) == 40:
            rows.append(CommitRow(sha=sha, subject=subject, author=author, date=date))
    return rows


def show_commit_full(repo: str, sha: str) -> str:
    """Full `git show` output (metadata + patch), read-only."""
    if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
        raise GitError("invalid commit")
    return _run(repo, ["show", "--no-color", "--pretty=medium", sha])


def short_oid(oid: str, n: int = 7) -> str:
    return oid[:n] if len(oid) >= n else oid
