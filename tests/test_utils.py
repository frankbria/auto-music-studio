"""Unit tests for acemusic utility helpers (US-2.3)."""

from acemusic.utils import make_filename, make_slug


class TestMakeSlug:
    def test_lowercases(self):
        assert make_slug("Hello World") == "hello-world"

    def test_spaces_become_hyphens(self):
        assert make_slug("a mellow folk song") == "a-mellow-folk-song"

    def test_strips_special_chars(self):
        # special chars are removed; consecutive hyphens collapse to one
        assert make_slug("rock & roll! (live)") == "rock-roll-live"

    def test_truncates_to_max_len(self):
        slug = make_slug("a" * 50)
        assert len(slug) <= 40

    def test_empty_string(self):
        assert make_slug("") == ""

    def test_collapses_multiple_hyphens(self):
        result = make_slug("hello   world")
        assert "--" not in result


class TestMakeFilename:
    def test_basic_format(self):
        name = make_filename("folk-song", "20240101120000", 1)
        assert name == "folk-song-20240101120000-1.wav"

    def test_custom_extension(self):
        name = make_filename("rock", "20240101", 2, ext="mp3")
        assert name == "rock-20240101-2.mp3"

    def test_index_in_name(self):
        assert make_filename("test", "ts", 3).endswith("-3.wav")
