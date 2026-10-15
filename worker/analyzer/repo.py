"""CodeCommit の clone と、モデルに渡すファイルの選別・分割。

方針:
- shallow clone（履歴は要らない）。
- 生成物・依存・バイナリ・ロックファイルは読まない（トークンの無駄）。
- 大きいファイルは先頭だけ。総量に上限。
- ツリー一覧は全ファイル（読まないものも名前は見せる）。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "out",
    ".next",
    ".nuxt",
    "__pycache__",
    ".venv",
    "venv",
    ".terraform",
    ".idea",
    ".vscode",
    "coverage",
    ".gradle",
    ".mvn",
    "bin",
    "obj",
}

IGNORED_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Gemfile.lock",
    "Cargo.lock",
    "composer.lock",
    "go.sum",
    ".terraform.lock.hcl",
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf", ".zip", ".gz", ".tar",
    ".jar", ".war", ".ear", ".class", ".so", ".dylib", ".dll", ".exe", ".bin", ".woff",
    ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".mov", ".parquet", ".pb", ".pyc", ".wasm",
    ".min.js", ".min.css", ".map",
}  # fmt: skip

# 設計を語るファイルは先に読む（チャンクの先頭に寄せる）
PRIORITY_NAMES = (
    "readme",
    "architecture",
    "design",
    "dockerfile",
    "docker-compose",
    "makefile",
    "pyproject.toml",
    "package.json",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "gemfile",
    "cargo.toml",
    "requirements",
    "serverless",
    "template.y",
    "samconfig",
    "buildspec",
    "appspec",
    "taskdef",
    ".github/workflows",
    "terraform",
    "cdk",
    "helm",
    "k8s",
    "kubernetes",
)


@dataclass(frozen=True)
class SourceFile:
    path: str  # repo 相対
    size: int
    text: str
    truncated: bool


@dataclass(frozen=True)
class Snapshot:
    repo: str
    commit: str
    tree: list[str]  # 全ファイルのパス（読まないものも含む）
    files: list[SourceFile]  # 読んだもの
    skipped_bytes: int  # 上限で読めなかった分


def clone(repo: str, ref: str, region: str, work_dir: str) -> tuple[Path, str]:
    """git-remote-codecommit で shallow clone。戻り値は (path, commit sha)。"""
    dest = Path(work_dir) / repo.replace("/", "_")
    if dest.exists():
        subprocess.run(["rm", "-rf", str(dest)], check=True)
    url = f"codecommit::{region}://{repo}"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", ref, url, str(dest)],
        check=True,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    sha = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return dest, sha


def _is_binary_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(s) for s in BINARY_SUFFIXES)


def _priority(path: str) -> int:
    lower = path.lower()
    for i, key in enumerate(PRIORITY_NAMES):
        if key in lower:
            return i
    return len(PRIORITY_NAMES) + lower.count("/")  # 浅いほど先


def walk(root: Path) -> list[str]:
    """無視ディレクトリを除いた全ファイルの相対パス。"""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            out.append(rel)
    return out


def read_text(path: Path, max_bytes: int) -> tuple[str, bool]:
    """先頭 max_bytes だけ読む。バイナリっぽければ空。"""
    with path.open("rb") as f:
        raw = f.read(max_bytes + 1)
    if b"\x00" in raw[:8000]:
        return "", False
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    return text, truncated


def snapshot(
    root: Path,
    repo: str,
    commit: str,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
) -> Snapshot:
    tree = walk(root)
    candidates = [
        p for p in tree if os.path.basename(p) not in IGNORED_FILES and not _is_binary_name(p)
    ]
    candidates.sort(key=_priority)

    files: list[SourceFile] = []
    total = 0
    skipped = 0
    for rel in candidates:
        full = root / rel
        try:
            size = full.stat().st_size
        except OSError:
            continue
        if size == 0:
            continue
        if total >= max_total_bytes:
            skipped += size
            continue
        text, truncated = read_text(full, max_file_bytes)
        if not text:
            continue
        files.append(SourceFile(path=rel, size=size, text=text, truncated=truncated))
        total += len(text.encode("utf-8", errors="ignore"))
    return Snapshot(repo=repo, commit=commit, tree=tree, files=files, skipped_bytes=skipped)


def render_tree(tree: list[str], limit: int = 4000) -> str:
    """ツリー一覧（全チャンクで共有する prefix なので cache が効く）。"""
    lines = tree[:limit]
    body = "\n".join(lines)
    if len(tree) > limit:
        body += f"\n... ({len(tree) - limit} more files)"
    return body


def render_file(f: SourceFile) -> str:
    note = " (truncated)" if f.truncated else ""
    return f"=== {f.path}{note} ===\n{f.text}\n"


def chunk(files: list[SourceFile], chunk_chars: int) -> list[list[SourceFile]]:
    """文字数で貪欲に詰める。1 ファイルが上限を超えても 1 チャンクには入れる。"""
    chunks: list[list[SourceFile]] = []
    cur: list[SourceFile] = []
    cur_len = 0
    for f in files:
        n = len(f.text) + len(f.path) + 16
        if cur and cur_len + n > chunk_chars:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(f)
        cur_len += n
    if cur:
        chunks.append(cur)
    return chunks
