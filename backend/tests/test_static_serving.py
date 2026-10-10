from __future__ import annotations

from app.main import safe_static_file


def test_serves_files_inside_the_dist_directory(tmp_path):
    (tmp_path / "assets").mkdir()
    f = tmp_path / "assets" / "app.js"
    f.write_text("x")
    assert safe_static_file(tmp_path, "assets/app.js") == f.resolve()


def test_unknown_paths_and_the_root_are_not_files(tmp_path):
    assert safe_static_file(tmp_path, "") is None
    assert (
        safe_static_file(tmp_path, "walk-test/3") is None
    )  # a client-side route, handled by the SPA fallback


def test_parent_directory_traversal_is_refused(tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    assert safe_static_file(root, "../secret.txt") is None
    assert safe_static_file(root, "assets/../../secret.txt") is None
