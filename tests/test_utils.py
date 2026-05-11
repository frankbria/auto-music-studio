"""Unit tests for acemusic utility helpers (US-2.3, US-5.1, US-6.1)."""

import pytest
import soundfile as sf

from acemusic.utils import (
    concatenate_audio,
    make_filename,
    make_slug,
    parse_time_string,
    slice_audio,
    snap_to_beat,
)


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


class TestParseTimeString:
    """Tests for parse_time_string() — time string to milliseconds."""

    def test_seconds_integer(self):
        assert parse_time_string("10s") == 10_000

    def test_seconds_float(self):
        assert parse_time_string("1.5s") == 1_500

    def test_zero_seconds(self):
        assert parse_time_string("0s") == 0

    def test_minutes_and_seconds(self):
        assert parse_time_string("1m30s") == 90_000

    def test_large_seconds(self):
        assert parse_time_string("90s") == 90_000

    def test_plain_int_as_string(self):
        assert parse_time_string("5") == 5_000

    def test_plain_float_as_string(self):
        assert parse_time_string("2.5") == 2_500

    def test_invalid_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot parse time"):
            parse_time_string("abc")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot parse time"):
            parse_time_string("")

    def test_negative_seconds_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_time_string("-5s")


class TestSnapToBeat:
    """Tests for snap_to_beat() — round time to nearest beat boundary."""

    def test_snap_at_120bpm_on_beat(self):
        # 120 BPM → beat_ms = 500ms; 1000ms is exactly on beat 2
        assert snap_to_beat(1000, 120) == 1000

    def test_snap_at_120bpm_rounds_down(self):
        # 120 BPM → beat_ms = 500ms; 749ms rounds to 500ms
        assert snap_to_beat(749, 120) == 500

    def test_snap_at_120bpm_rounds_up(self):
        # 120 BPM → beat_ms = 500ms; 750ms rounds up to 1000ms
        assert snap_to_beat(750, 120) == 1000

    def test_snap_at_60bpm(self):
        # 60 BPM → beat_ms = 1000ms
        assert snap_to_beat(1400, 60) == 1000

    def test_snap_at_60bpm_rounds_up(self):
        assert snap_to_beat(1500, 60) == 2000

    def test_snap_at_90bpm(self):
        # 90 BPM → beat_ms ≈ 666.67ms; 700ms closer to 666.67 than 1333.33 → 667
        result = snap_to_beat(700, 90)
        assert result == round(666.67)

    def test_snap_zero_stays_zero(self):
        assert snap_to_beat(0, 120) == 0


# ---------------------------------------------------------------------------
# Audio utilities (US-6.1)
# ---------------------------------------------------------------------------


class TestConcatenateAudio:
    """Tests for concatenate_audio — joins two WAV files end-to-end."""

    def test_output_file_created(self, tmp_path, write_tone):
        a = tmp_path / "a.wav"
        b = tmp_path / "b.wav"
        out = tmp_path / "joined.wav"
        write_tone(a, frequency=440.0, duration_s=1.0)
        write_tone(b, frequency=660.0, duration_s=1.0)

        concatenate_audio(a, b, out)

        assert out.exists()

    def test_duration_is_sum_of_inputs(self, tmp_path, write_tone):
        a = tmp_path / "a.wav"
        b = tmp_path / "b.wav"
        out = tmp_path / "joined.wav"
        write_tone(a, frequency=440.0, duration_s=1.0)
        write_tone(b, frequency=660.0, duration_s=0.5)

        concatenate_audio(a, b, out)

        data, sr = sf.read(str(out))
        duration = len(data) / sr
        assert abs(duration - 1.5) < 0.01

    def test_preserves_sample_rate_of_first(self, tmp_path, write_tone):
        a = tmp_path / "a.wav"
        b = tmp_path / "b.wav"
        out = tmp_path / "joined.wav"
        write_tone(a, frequency=440.0, duration_s=0.5, sample_rate=44100)
        write_tone(b, frequency=660.0, duration_s=0.5, sample_rate=44100)

        concatenate_audio(a, b, out)

        _, sr = sf.read(str(out))
        assert sr == 44100

    def test_missing_original_raises(self, tmp_path, write_tone):
        b = tmp_path / "b.wav"
        write_tone(b, frequency=440.0, duration_s=0.5)
        with pytest.raises((FileNotFoundError, RuntimeError, OSError)):
            concatenate_audio(tmp_path / "missing.wav", b, tmp_path / "out.wav")

    def test_missing_extension_raises(self, tmp_path, write_tone):
        a = tmp_path / "a.wav"
        write_tone(a, frequency=440.0, duration_s=0.5)
        with pytest.raises((FileNotFoundError, RuntimeError, OSError)):
            concatenate_audio(a, tmp_path / "missing.wav", tmp_path / "out.wav")


class TestSliceAudio:
    """Tests for slice_audio — trims audio to the leading head_seconds."""

    def test_output_file_created(self, tmp_path, write_tone):
        src = tmp_path / "src.wav"
        out = tmp_path / "sliced.wav"
        write_tone(src, frequency=440.0, duration_s=2.0)

        slice_audio(src, 1.0, out)

        assert out.exists()

    def test_duration_matches_requested(self, tmp_path, write_tone):
        src = tmp_path / "src.wav"
        out = tmp_path / "sliced.wav"
        write_tone(src, frequency=440.0, duration_s=2.0)

        slice_audio(src, 1.0, out)

        data, sr = sf.read(str(out))
        duration = len(data) / sr
        assert abs(duration - 1.0) < 0.01

    def test_zero_seconds_raises(self, tmp_path, write_tone):
        src = tmp_path / "src.wav"
        write_tone(src, frequency=440.0, duration_s=1.0)
        with pytest.raises(ValueError):
            slice_audio(src, 0.0, tmp_path / "out.wav")

    def test_negative_seconds_raises(self, tmp_path, write_tone):
        src = tmp_path / "src.wav"
        write_tone(src, frequency=440.0, duration_s=1.0)
        with pytest.raises(ValueError):
            slice_audio(src, -1.0, tmp_path / "out.wav")

    def test_seconds_exceeds_duration_raises(self, tmp_path, write_tone):
        src = tmp_path / "src.wav"
        write_tone(src, frequency=440.0, duration_s=1.0)
        with pytest.raises(ValueError):
            slice_audio(src, 5.0, tmp_path / "out.wav")

    def test_missing_input_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, RuntimeError, OSError)):
            slice_audio(tmp_path / "missing.wav", 0.5, tmp_path / "out.wav")
