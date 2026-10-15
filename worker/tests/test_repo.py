from pathlib import Path

from analyzer.repo import SourceFile, chunk, render_tree, snapshot, walk


def _make_repo(root: Path) -> None:
    (root / "README.md").write_text("# hello\n")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hi')\n" * 50)
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.js").write_text("ignored")
    (root / "package-lock.json").write_text("{}")
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x00")
    (root / "big.txt").write_text("x" * 10_000)


def test_walk_skips_ignored_dirs(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    tree = walk(tmp_path)
    assert "README.md" in tree
    assert "src/app.py" in tree
    assert not any(p.startswith("node_modules") for p in tree)


def test_snapshot_filters_and_truncates(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    snap = snapshot(tmp_path, "r", "abc", max_file_bytes=1000, max_total_bytes=100_000)
    paths = [f.path for f in snap.files]
    assert "README.md" in paths
    assert "package-lock.json" not in paths
    assert "logo.png" not in paths
    big = next(f for f in snap.files if f.path == "big.txt")
    assert big.truncated and len(big.text) == 1000
    # README は設計を語るので先頭
    assert paths[0] == "README.md"


def test_snapshot_total_cap(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    # 上限は「超えたら以降を読まない」ソフトキャップ：README(8B) の後に 1 件読んで止まる
    snap = snapshot(tmp_path, "r", "abc", max_file_bytes=100_000, max_total_bytes=20)
    assert len(snap.files) == 2
    assert snap.skipped_bytes > 0


def test_chunk_packs_by_chars() -> None:
    files = [SourceFile(path=f"f{i}", size=10, text="a" * 100, truncated=False) for i in range(10)]
    # 1 file = 100 + len("fN") + 16 = 118 chars -> 3 per chunk at 360
    chunks = chunk(files, chunk_chars=360)
    assert [len(c) for c in chunks] == [3, 3, 3, 1]
    assert sum(len(c) for c in chunks) == 10


def test_chunk_oversized_single_file() -> None:
    files = [SourceFile(path="huge", size=1, text="a" * 1000, truncated=False)]
    assert len(chunk(files, chunk_chars=10)) == 1


def test_render_tree_limit() -> None:
    out = render_tree([f"p{i}" for i in range(10)], limit=3)
    assert "7 more files" in out
