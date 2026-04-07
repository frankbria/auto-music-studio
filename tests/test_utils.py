"""Unit tests for acemusic utility helpers (US-2.3)."""

from acemusic.utils import make_filename, make_slug


class TestMakeSlug:
    """Tests for the make_slug() prompt-to-slug helper."""

    def test_lowercases(self):
        """Converts uppercase input to lowercase."""
        assert make_slug("Hello World") == "hello-world"

    def test_spaces_become_hyphens(self):
        """Replaces spaces with hyphens."""
        assert make_slug("a mellow folk song") == "a-mellow-folk-song"

    def test_strips_special_chars(self):
        """Strips non-alphanumeric characters; collapses consecutive hyphens to one."""
        assert make_slug("rock & roll! (live)") == "rock-roll-live"

    def test_truncates_to_max_len(self):
        """Truncates the slug to the configured max length."""
        slug = make_slug("a" * 50)
        assert len(slug) <= 40

    def test_empty_string(self):
        """Returns an empty string when given an empty prompt."""
        assert make_slug("") == ""

    def test_collapses_multiple_hyphens(self):
        """Multiple consecutive spaces do not produce double hyphens."""
        result = make_slug("hello   world")
        assert "--" not in result


class TestMakeFilename:
    """Tests for the make_filename() output-filename builder."""

    def test_basic_format(self):
        """Produces the expected slug-timestamp-index.wav pattern."""
        name = make_filename("folk-song", "20240101120000", 1)
        assert name == "folk-song-20240101120000-1.wav"

    def test_custom_extension(self):
        """Uses the supplied extension instead of the default wav."""
        name = make_filename("rock", "20240101", 2, ext="mp3")
        assert name == "rock-20240101-2.mp3"

    def test_index_in_name(self):
        """Clip index appears as the last numeric component before the extension."""
        assert make_filename("test", "ts", 3).endswith("-3.wav")
