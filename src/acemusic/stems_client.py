"""AI-based stem separation client using demucs (US-5.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    import demucs.apply as demucs_apply
    import demucs.pretrained as demucs_pretrained
    import torch
    import torchaudio as ta
except ImportError:  # pragma: no cover
    demucs_apply = None  # type: ignore[assignment]
    demucs_pretrained = None  # type: ignore[assignment]
    torch = None  # type: ignore[assignment]
    ta = None  # type: ignore[assignment]

STEM_LABELS: list[str] = ["drums", "bass", "other", "vocals"]


class StemsError(Exception):
    """Raised when stem separation fails."""


class StemsClient:
    """Encapsulates demucs-based stem separation."""

    def __init__(self, model_name: str = "htdemucs") -> None:
        self._model_name = model_name
        self._model = None

    def _load_model(self):
        if demucs_pretrained is None:
            raise StemsError("demucs is not installed. Install with: uv pip install 'acemusic[audio-ml]'")
        if self._model is None:
            self._model = demucs_pretrained.get_model(self._model_name)
            self._model.eval()
        return self._model

    def separate(
        self,
        audio_path: Path | str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict[str, torch.Tensor]:
        """Separate an audio file into stems.

        Args:
            audio_path: Path to the input audio file.
            progress_callback: Optional callable receiving status messages.

        Returns:
            Dict mapping stem label to tensor of shape [channels, samples].

        Raises:
            StemsError: If the file is missing or separation fails.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise StemsError(f"Input file not found: {audio_path}")

        if progress_callback:
            progress_callback("Loading model...")

        try:
            model = self._load_model()
        except Exception as exc:
            raise StemsError(f"Failed to load model: {exc}") from exc

        if progress_callback:
            progress_callback("Loading audio...")

        try:
            wav, sr = ta.load(str(audio_path))
        except Exception as exc:
            raise StemsError(f"Failed to load audio: {exc}") from exc

        # Resample if needed
        if sr != model.samplerate:
            wav = ta.functional.resample(wav, sr, model.samplerate)

        if progress_callback:
            progress_callback("Separating stems...")

        try:
            ref = wav.mean(0)
            wav = (wav - ref.mean()) / ref.std()
            sources = demucs_apply.apply_model(model, wav[None], progress=False)
            sources = sources * ref.std() + ref.mean()
        except Exception as exc:
            raise StemsError(f"Separation failed: {exc}") from exc

        # Map model source order to labelled dict
        result = {}
        for idx, label in enumerate(model.sources):
            result[label] = sources[0, idx]

        return result

    def save_stems(
        self,
        stems: dict[str, torch.Tensor],
        output_dir: Path | str,
        base_name: str,
        sample_rate: int = 44100,
        output_format: str = "wav",
    ) -> list[Path]:
        """Save separated stems to files.

        Args:
            stems: Dict of label → tensor [channels, samples].
            output_dir: Directory to write stem files into.
            base_name: Base filename (without extension).
            sample_rate: Audio sample rate.
            output_format: Output format ('wav' or 'flac').

        Returns:
            List of paths to the written stem files.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        paths = []
        for label in STEM_LABELS:
            if label not in stems:
                continue
            path = output_dir / f"{base_name}-{label}.{output_format}"
            ta.save(str(path), stems[label], sample_rate)
            paths.append(path)

        return paths
