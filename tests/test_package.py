"""Tests for acemusic package bootstrap (US-1.1)."""


def test_import_acemusic():
    """uv run python -c 'import acemusic' must succeed."""
    import acemusic  # noqa: F401


def test_version_string():
    """Package must expose a __version__ string."""
    import acemusic

    assert hasattr(acemusic, "__version__")
    assert isinstance(acemusic.__version__, str)
    assert acemusic.__version__ == "0.1.0"
