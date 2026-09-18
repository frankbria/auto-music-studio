"""Guard for the plugin's third-party notices (#499).

Every licence below that requires a notice in a binary distribution must travel
with the plug-in, and every CI package of the plug-in must carry the file.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "plugin" / "THIRD_PARTY_NOTICES.md"
WORKFLOW = ROOT / ".github" / "workflows" / "plugin.yml"

COMPILED = [
    "Steinberg VST3 SDK",
    "FLAC",
    "Ogg Vorbis",
    "libpng",
    "Independent JPEG Group",
    "zlib",
    "HarfBuzz",
    "SheenBidi",
    "AudioUnitSDK",
]
EXCLUDED = ["ASIO", "AAX", "LV2", "Oboe", "GLEW", "CHOC", "QuickJS", "Box2D"]


def test_every_compiled_component_has_a_notice() -> None:
    headings = [line for line in NOTICES.read_text().splitlines() if line.startswith("## ")]
    missing = [c for c in COMPILED if not any(c in h for h in headings)]
    assert not missing, f"no notice section for: {missing}"


def test_ijg_acknowledgement_is_verbatim() -> None:
    statement = "this software is based in part on the work of the independent jpeg group"
    assert statement in NOTICES.read_text().lower()


def test_apache_licence_text_is_included() -> None:
    text = NOTICES.read_text()
    assert "Apache License" in text and "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in text


def test_excluded_components_are_named() -> None:
    text = NOTICES.read_text()
    excluded = text[text.index("## Not compiled into this build") :]
    missing = [c for c in EXCLUDED if c not in excluded]
    assert not missing, f"not listed as excluded: {missing}"


def test_every_uploaded_package_carries_the_notices() -> None:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["build"]["steps"]
    uploads = [s for s in steps if "upload-artifact" in s.get("uses", "")]
    assert uploads, "plugin.yml uploads no package"
    package_dir = "plugin/dist"
    staged = any("THIRD_PARTY_NOTICES.md" in s.get("run", "") and "dist" in s.get("run", "") for s in steps)
    assert staged, "no step copies THIRD_PARTY_NOTICES.md into the package directory"
    for upload in uploads:
        assert upload["with"]["path"].rstrip("/") == package_dir, upload["with"]["path"]
        assert upload["with"].get("if-no-files-found") == "error"
