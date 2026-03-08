"""文件系统工具单元测试。"""

from pathlib import Path

from tools.filesystem import get_tree, list_directory, read_file, search_in_files


def test_get_tree(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Hello")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")

    result = get_tree(str(tmp_path))
    assert "error" not in result
    assert "README.md" in result["tree"]
    assert "src/" in result["tree"]
    assert "main.py" in result["tree"]
    assert result["total_files"] >= 2


def test_get_tree_skips_hidden(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / "app.py").write_text("x")

    result = get_tree(str(tmp_path))
    assert ".git" not in result["tree"]
    assert "app.py" in result["tree"]


def test_list_directory(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("hello")
    (tmp_path / "subdir").mkdir()

    result = list_directory(str(tmp_path))
    assert result["count"] == 2
    names = {item["name"] for item in result["items"]}
    assert "file.txt" in names
    assert "subdir" in names


def test_list_directory_not_dir(tmp_path: Path) -> None:
    result = list_directory(str(tmp_path / "nonexistent"))
    assert "error" in result


def test_read_file(tmp_path: Path) -> None:
    content = "Hello, world! " * 100
    (tmp_path / "test.txt").write_text(content)

    result = read_file(str(tmp_path / "test.txt"))
    assert "error" not in result
    assert result["content"].startswith("Hello, world!")
    assert result["was_truncated"] is False


def test_read_file_truncation(tmp_path: Path) -> None:
    content = "x" * 10000
    (tmp_path / "big.txt").write_text(content)

    result = read_file(str(tmp_path / "big.txt"), max_chars=100)
    assert result["was_truncated"] is True
    assert len(result["content"]) == 100


def test_read_file_binary_rejected(tmp_path: Path) -> None:
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    result = read_file(str(tmp_path / "image.png"))
    assert "error" in result


def test_read_file_not_found(tmp_path: Path) -> None:
    result = read_file(str(tmp_path / "nope.txt"))
    assert "error" in result


def test_search_in_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def hello():\n    pass")
    (tmp_path / "b.py").write_text("def world():\n    pass")

    result = search_in_files("hello", str(tmp_path))
    assert result["match_count"] == 1
    assert result["matches"][0]["file"] == "a.py"


def test_search_in_files_no_match(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def hello():\n    pass")
    result = search_in_files("nonexistent_string_xyz", str(tmp_path))
    assert result["match_count"] == 0
