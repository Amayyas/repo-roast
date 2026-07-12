from pathlib import Path


def test_py_typed_marker_exists() -> None:
    assert (Path(__file__).parents[1] / "src/repo_roast/py.typed").is_file()
