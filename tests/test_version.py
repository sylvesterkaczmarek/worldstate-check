from importlib.metadata import version

from worldstate_check import __version__


def test_runtime_version_matches_package_metadata():
    assert __version__ == version("worldstate-check")
