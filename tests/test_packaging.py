from importlib.resources import files


def test_py_typed_ships_with_the_installed_package() -> None:
    assert (files("repo_roast") / "py.typed").is_file()
